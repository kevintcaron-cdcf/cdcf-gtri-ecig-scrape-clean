import ast
import json
import logging
import os
import re
import sys
import time
import warnings

from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import pandas as pd
import pyodbc
from dotenv import load_dotenv
from openai import OpenAI
from tqdm import tqdm


# ============================================================================
# ENVIRONMENT / PROJECT PATHS
# ============================================================================

# Absolute path: <repo-root>/ai_pipeline
PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))

# Absolute path: <repo-root>
PROJECT_ROOT = os.path.dirname(PIPELINE_DIR)

# Loads: <repo-root>/ai_pipeline/.env
ENV_FILE = os.path.join(PIPELINE_DIR, ".env")
load_dotenv(ENV_FILE, override=True)

warnings.filterwarnings(
    "ignore",
    message=r".*pandas only supports SQLAlchemy connectable.*",
    category=UserWarning
)


# ============================================================================
# CONFIGURATION
# ============================================================================

# Outputs will be written to:
# ai_pipeline/outputs/
OUTPUT_DIR = os.path.join(PIPELINE_DIR, "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

INPUT_TABLE = os.getenv("INPUT_TABLE", "dbo.ecig_product")
FLAVOR_OUTPUT_TABLE = os.getenv(
    "FLAVOR_ATTRIBUTE_OUTPUT_TABLE",
    "dbo.ecig_flavor_attributes"
)
MODEL_OUTPUT_TABLE = os.getenv(
    "MODEL_ATTRIBUTE_OUTPUT_TABLE",
    "dbo.ecig_model_attributes"
)

PROCESS_BATCH_SIZE = int(os.getenv("PROCESS_BATCH_SIZE", "5000"))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "500"))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "10"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "1"))
RETRY_DELAY = float(os.getenv("RETRY_DELAY", "2"))
RATE_LIMIT_DELAY = float(os.getenv("RATE_LIMIT_DELAY", "0.1"))

TEST_MODE = os.getenv("TEST_MODE", "true").lower() == "true"
FLAVOR_TEST_ROWS = int(os.getenv("FLAVOR_TEST_ROWS", "100"))
MODEL_TEST_ROWS = int(os.getenv("MODEL_TEST_ROWS", "100"))

API_KEY = os.getenv("CORE_API_KEY")
BASE_URL = os.getenv(
    "CORE_BASE_URL",
    "https://litellm.core.gtri.org/v1"
).strip().strip('"').strip("'")

FLAVOR_EXTRACTION_MODEL = os.getenv("FLAVOR_EXTRACTION_MODEL")
FLAVOR_CLASSIFICATION_MODEL = os.getenv("FLAVOR_CLASSIFICATION_MODEL")
MODEL_EXTRACTION_MODEL = os.getenv("BRAND_EXTRACTION_MODEL")


# ============================================================================
# OUTPUT FILES
# ============================================================================


FLAVOR_EXTRACTION_OUTPUT_FILE = os.path.join(OUTPUT_DIR, "flavor_extraction_output.csv")
FLAVOR_FLATTENED_OUTPUT_FILE = os.path.join(OUTPUT_DIR, "flavor_flattened_output.csv")
FLAVOR_CLASSIFIED_OUTPUT_FILE = os.path.join(OUTPUT_DIR, "flavor_classified_output.csv")
FLAVOR_CHECKPOINT_FILE = os.path.join(OUTPUT_DIR, "flavor_attribute_pipeline_checkpoint.jsonl")
FLAVOR_METRICS_FILE = os.path.join(OUTPUT_DIR, "flavor_attribute_pipeline_metrics.json")
MODEL_EXTRACTION_OUTPUT_FILE = os.path.join(OUTPUT_DIR, "brand_extraction_output.csv")
MODEL_RESOLVED_OUTPUT_FILE = os.path.join(OUTPUT_DIR, "brand_resolved_output.csv")
MODEL_FINAL_OUTPUT_FILE = os.path.join(OUTPUT_DIR, "brand_extraction_final_output.csv")
MODEL_BRAND_LINE_MAP_FILE = os.path.join(OUTPUT_DIR, "brand_product_line_map.csv")
MODEL_CHECKPOINT_FILE = os.path.join(OUTPUT_DIR, "model_attribute_pipeline_checkpoint.jsonl")
MODEL_METRICS_FILE = os.path.join(OUTPUT_DIR, "model_attribute_pipeline_metrics.json")
LOG_FILE = os.path.join(OUTPUT_DIR, "feature_extraction_pipeline.log")
ERROR_LOG_FILE = os.path.join(OUTPUT_DIR,"feature_extraction_errors.csv")


# ============================================================================
# LOGGING AND CLIENT
# ============================================================================

formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - %(message)s"
)

file_handler = logging.FileHandler(LOG_FILE)
console_handler = logging.StreamHandler(sys.stdout)

file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

logger = logging.getLogger("feature_extraction_pipeline")
logger.setLevel(logging.INFO)
logger.handlers.clear()
logger.addHandler(file_handler)
logger.addHandler(console_handler)
logger.propagate = False

for logger_name in [
    "httpx",
    "httpcore",
    "openai",
    "openai._base_client"
]:
    noisy_logger = logging.getLogger(logger_name)
    noisy_logger.setLevel(logging.WARNING)
    noisy_logger.propagate = False

client = OpenAI(
    api_key=API_KEY,
    base_url=BASE_URL
)


# ============================================================================
# SHARED HELPERS
# ============================================================================

def clean_value(value) -> str:
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass

    return str(value)


def clean_text(value) -> str:
    return "".join(
        character
        for character in clean_value(value)
        if ord(character) < 128
    )


def clean_optional(value) -> str:
    value = clean_value(value).strip()

    if value.lower() in {"", "nan", "none", "null"}:
        return ""

    return value


def required_value(value):
    value = clean_value(value).strip()
    return value if value else None


def normalize_unique_id(value) -> str:
    return clean_value(value).strip()


def normalize_key(value) -> str:
    return clean_optional(value).lower().strip()


def uppercase_database_values(
    df: pd.DataFrame,
    columns: List[str]
) -> pd.DataFrame:
    result = df.copy()

    for column in columns:
        if column in result.columns:
            result[column] = (
                result[column]
                .fillna("")
                .astype(str)
                .str.strip()
                .str.upper()
            )

    return result


def sort_by_product_id(
    df: pd.DataFrame
) -> pd.DataFrame:
    if df.empty or "id" not in df.columns:
        return df

    result = df.copy()
    result["_product_sort"] = pd.to_numeric(
        result["id"],
        errors="coerce"
    )

    sort_columns = ["_product_sort"]

    if "unique_id" in result.columns:
        sort_columns.append("unique_id")

    if "flavor" in result.columns:
        sort_columns.append("flavor")

    result = result.sort_values(
        by=sort_columns,
        ascending=[True] * len(sort_columns),
        na_position="last"
    )

    return result.drop(
        columns=["_product_sort"]
    ).reset_index(drop=True)


def get_db_connection():
    server = os.getenv("DB_SERVER")
    database = os.getenv("DB_NAME")
    username = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")
    driver = os.getenv(
        "DB_DRIVER",
        "ODBC Driver 18 for SQL Server"
    )
    encrypt = os.getenv("DB_ENCRYPT", "yes")
    trust_cert = os.getenv(
        "DB_TRUST_SERVER_CERTIFICATE",
        "no"
    )
    timeout = os.getenv("DB_CONNECTION_TIMEOUT", "30")

    required = {
        "DB_SERVER": server,
        "DB_NAME": database,
        "DB_USER": username,
        "DB_PASSWORD": password
    }

    missing = [
        key
        for key, value in required.items()
        if not value
    ]

    if missing:
        raise ValueError(
            "Missing .env variables: "
            + ", ".join(missing)
        )

    connection_string = (
        f"DRIVER={{{driver}}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={username};"
        f"PWD={password};"
        f"Encrypt={encrypt};"
        f"TrustServerCertificate={trust_cert};"
        f"Connection Timeout={timeout};"
    )

    return pyodbc.connect(connection_string)


def append_csv_history(
    current_df: pd.DataFrame,
    output_path: str
):
    """
    Append current-run rows to a running CSV.

    No deduplication is performed intentionally.
    """
    if current_df is None or current_df.empty:
        return

    output_df = current_df.copy().fillna("")
    file_exists = os.path.exists(output_path)

    output_df.to_csv(
        output_path,
        mode="a",
        header=not file_exists,
        index=False
    )

    try:
        with open(
            output_path,
            "r",
            encoding="utf-8"
        ) as file:
            total_rows = max(
                sum(1 for _ in file) - 1,
                0
            )
    except OSError:
        total_rows = len(output_df)

    logger.info(
        "Appended %s rows to %s. Total rows=%s.",
        len(output_df),
        output_path,
        total_rows
    )


def write_jsonl_checkpoint(
    records: List[Dict],
    output_path: str
):
    with open(
        output_path,
        "w",
        encoding="utf-8"
    ) as file:
        for record in records:
            file.write(
                json.dumps(
                    record,
                    ensure_ascii=True
                ) + "\n"
            )

def append_error_log(
    pipeline: str,
    stage: str,
    records: List[Dict]
):
    """
    Append failed API/parsing records to the current run's error CSV.
    ERROR_LOG_FILE is reset at the beginning of each pipeline run.
    """
    if not records:
        return

    error_rows = []

    for record in records:
        error_rows.append({
            "timestamp_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "pipeline": pipeline,
            "stage": stage,
            "product_id": clean_value(
                record.get("id", "")
            ),
            "unique_id": normalize_unique_id(
                record.get("unique_id", "")
            ),
            "product_name": clean_value(
                record.get("product_name", "")
            ),
            "flavor": clean_value(
                record.get("flavor", "")
            ),
            "flavor_description": clean_value(
                record.get("flavor_description", "")
            ),
            "error_message": clean_value(
                record.get("error_message", "")
            ),
            "raw_llm_response": clean_value(
                record.get("raw_llm_response", "")
            )
        })

    error_df = pd.DataFrame(error_rows)
    file_exists = os.path.exists(ERROR_LOG_FILE)

    error_df.to_csv(
        ERROR_LOG_FILE,
        mode="a",
        header=not file_exists,
        index=False,
        encoding="utf-8"
    )

    logger.warning(
        "Logged %s %s error(s) to %s.",
        len(error_df),
        stage,
        ERROR_LOG_FILE
    )

# ============================================================================
# PIPELINE COUNTS
# ============================================================================

def get_pipeline_counts():
    query = f"""
    WITH source_pairs AS
    (
        SELECT DISTINCT
            p.id AS product_id,
            ISNULL(p.unique_id, '') AS unique_id
        FROM {INPUT_TABLE} AS p
        WHERE p.id IS NOT NULL
    ),
    processed_flavor_pairs AS
    (
        SELECT DISTINCT
            product_id,
            ISNULL(unique_id, '') AS unique_id
        FROM {FLAVOR_OUTPUT_TABLE}
    ),
    processed_model_pairs AS
    (
        SELECT DISTINCT
            product_id,
            ISNULL(unique_id, '') AS unique_id
        FROM {MODEL_OUTPUT_TABLE}
    )
    SELECT
        (SELECT COUNT(*) FROM {INPUT_TABLE}),
        (
            SELECT COUNT(DISTINCT p.id)
            FROM {INPUT_TABLE} AS p
            WHERE p.id IS NOT NULL
        ),
        (
            SELECT COUNT(DISTINCT p.unique_id)
            FROM {INPUT_TABLE} AS p
            WHERE p.unique_id IS NOT NULL
              AND LTRIM(RTRIM(p.unique_id)) <> ''
        ),
        (
            SELECT COUNT(*)
            FROM {INPUT_TABLE} AS p
            WHERE p.unique_id IS NULL
        ),
        (SELECT COUNT(*) FROM {FLAVOR_OUTPUT_TABLE}),
        (SELECT COUNT(*) FROM {MODEL_OUTPUT_TABLE}),
        (
            SELECT COUNT(*)
            FROM source_pairs AS s
            WHERE EXISTS
            (
                SELECT 1
                FROM processed_flavor_pairs AS f
                WHERE f.product_id = s.product_id
                  AND f.unique_id = s.unique_id
            )
        ),
        (
            SELECT COUNT(*)
            FROM source_pairs AS s
            WHERE EXISTS
            (
                SELECT 1
                FROM processed_model_pairs AS m
                WHERE m.product_id = s.product_id
                  AND m.unique_id = s.unique_id
            )
        )
    """

    conn = get_db_connection()

    try:
        cursor = conn.cursor()
        cursor.execute(query)
        row = cursor.fetchone()

        return {
            "total_source_rows": int(row[0] or 0),
            "source_product_ids": int(row[1] or 0),
            "source_unique_ids": int(row[2] or 0),
            "null_source_unique_ids": int(row[3] or 0),
            "flavor_attribute_rows": int(row[4] or 0),
            "model_attribute_rows": int(row[5] or 0),
            "processed_flavor_pairs": int(row[6] or 0),
            "processed_model_pairs": int(row[7] or 0)
        }

    finally:
        conn.close()


def print_pipeline_counts():
    counts = get_pipeline_counts()

    logger.info("=" * 70)
    logger.info("PIPELINE COUNTS")
    logger.info("=" * 70)
    logger.info(
        "Total source rows: %s",
        f"{counts['total_source_rows']:,}"
    )
    logger.info(
        "Distinct product IDs: %s",
        f"{counts['source_product_ids']:,}"
    )
    logger.info(
        "Distinct unique IDs: %s",
        f"{counts['source_unique_ids']:,}"
    )
    logger.info(
        "Source rows with NULL unique_id: %s",
        f"{counts['null_source_unique_ids']:,}"
    )
    logger.info(
        "Rows in %s: %s",
        FLAVOR_OUTPUT_TABLE,
        f"{counts['flavor_attribute_rows']:,}"
    )
    logger.info(
        "Rows in %s: %s",
        MODEL_OUTPUT_TABLE,
        f"{counts['model_attribute_rows']:,}"
    )
    logger.info(
        "Processed flavor pairs: %s",
        f"{counts['processed_flavor_pairs']:,}"
    )
    logger.info(
        "Processed model pairs: %s",
        f"{counts['processed_model_pairs']:,}"
    )
    logger.info("=" * 70)


# ============================================================================
# FLAVOR SOURCE LOADING
# ============================================================================

def load_flavor_products_for_processing() -> pd.DataFrame:
    rows_to_process = (
        FLAVOR_TEST_ROWS
        if TEST_MODE
        else PROCESS_BATCH_SIZE
    )

    query = f"""
    SELECT TOP {rows_to_process}
        p.id,
        p.unique_id,
        p.product_name,
        p.site_name,
        p.url,
        p.site_category,
        p.flavor_text,
        p.description
    FROM {INPUT_TABLE} AS p
    WHERE p.id IS NOT NULL
      AND NOT EXISTS
      (
          SELECT 1
          FROM {FLAVOR_OUTPUT_TABLE} AS fa
          WHERE fa.product_id = p.id
            AND ISNULL(fa.unique_id, '') =
                ISNULL(p.unique_id, '')
      )
    ORDER BY
        p.id ASC,
        ISNULL(p.unique_id, '') ASC
    """

    conn = get_db_connection()

    try:
        df = pd.read_sql_query(query, conn)
    finally:
        conn.close()

    df = df.fillna("")
    df["unique_id"] = df["unique_id"].apply(
        normalize_unique_id
    )

    logger.info(
        "Loaded %s rows for flavor attributes. TEST_ROWS=%s",
        len(df),
        FLAVOR_TEST_ROWS if TEST_MODE else "disabled"
    )

    return df


# ============================================================================
# FLAVOR JSON HELPERS
# ============================================================================

def try_parse_flavor_json(
    text: str
) -> Optional[List[Dict]]:
    try:
        parsed = json.loads(text)

        if not isinstance(parsed, list):
            return None

        if all(
            isinstance(item, dict)
            and "flavor" in item
            for item in parsed
        ):
            return parsed

        if all(
            isinstance(item, str)
            for item in parsed
        ):
            return [
                {
                    "flavor": item.strip(),
                    "description": None
                }
                for item in parsed
                if item.strip()
            ]

    except json.JSONDecodeError:
        return None

    return None


def extract_json_spans(
    text: str
) -> List[str]:
    spans = []
    depth = 0
    start = None

    for index, character in enumerate(text):
        if character == "[":
            if depth == 0:
                start = index

            depth += 1

        elif character == "]":
            depth -= 1

            if depth == 0 and start is not None:
                spans.append(
                    text[start:index + 1]
                )
                start = None

    if start is not None:
        spans.append(text[start:])

    return spans


def clean_flavor_json_string(
    raw_content: str
) -> Optional[List[Dict]]:
    if not raw_content:
        return None

    text = raw_content.strip()
    text = re.sub(
        r"^```(?:json)?\s*\n?",
        "",
        text,
        flags=re.IGNORECASE
    )
    text = re.sub(
        r"\n?```\s*$",
        "",
        text
    ).strip()

    for candidate in reversed(
        extract_json_spans(text)
    ):
        candidate = re.sub(
            r",\s*(\]|\})",
            r"\1",
            candidate
        )

        parsed = try_parse_flavor_json(candidate)

        if parsed is not None:
            return parsed

        if '"' not in candidate:
            parsed = try_parse_flavor_json(
                candidate.replace("'", '"')
            )

            if parsed is not None:
                return parsed

    return None


# ============================================================================
# ORIGINAL FLAVOR EXTRACTION PROMPT
# ============================================================================

def build_flavor_extraction_prompt(
    row: Dict
) -> str:
    product_name = clean_text(
        row.get("product_name", "")
    )
    description = clean_text(
        row.get("description", "")
    )
    flavor_text = clean_text(
        row.get("flavor_text", "")
    )

    return f"""Extract all flavor names from this vape product information.

Product Name: {product_name}
Description: {description}
Flavor Text: {flavor_text}

CRITICAL RULES - READ CAREFULLY:
1. Keep ALL multi-word flavor names as a SINGLE COMPLETE PHRASE - NEVER split them. If a flavor has multiple names separated by "/" or "&" (e.g. "Banana Ice / Banana Freeze"), keep them together as one flavor
2. Always extract the complete flavor name from the Product Name first - this is the primary source. Flavor is typically the last word(s) after brand/model, but can appear anywhere. Extract the FULL flavor name from Product Name - don't shorten it or extract only part of it.
3. If Product Name HAS a flavor, use the description/Flavor Text to fill the "description" field (taste notes), NOT as the flavor name source
4. IF the flavor name contains parentheses like "Flavor Name (Descriptor)", extract "Flavor Name" as the flavor and "Descriptor" as the description
5. Remove brand names (Elf Bar, Lost Mary, Hyde, NKD, Vuse, JUUL, Puff Bar, Custard Monster, HandShake, Pod Juice, HQD, SMOK, Lost Vape, Yogi, Nexa etc.)
6. Remove product codes (BC5000, MO5000, OS5000, 15K, 20K, 7000, 4000, etc.)
7. Remove generic product words (Nicotine, Disposable, Recharge, E-Liquid, E-juice, 30ml) when NOT part of the flavor
8. Keep "Ice", "Freeze", "Cool", "Menthol" as part of the flavor name when they appear with other flavor words
9. Extract EVERY SINGLE flavor from lists exactly as written - do NOT deduplicate or skip flavors that share words. Each flavor listed is a SEPARATE product. 
   Before extracting, COUNT how many flavor names appear (look for patterns like "Name -" or "Name:" in paragraphs). Then extract exactly that many. DO NOT use deduplication logic.
10. If the product is hardware (coil, mod, kit, pod system, cartridge, battery) AND there are NO flavor names or flavor lists anywhere in Product Name, Description, or Flavor Text, return []
11. If the Product Name has NO flavor, look for flavor lists in the Description under sections like "Flavors:", "Available Flavors:" "Lab Reports:" or similar headings

Examples of correct extraction:
- "Hyde Edge Recharge Pina Colada" -> [{{"flavor": "Pina Colada", "description": null}}]
- "Crystal Clear NEXA Flex Visible Disposable Vape" -> [{{"flavor": "Crystal Clear", "description": null}}]
- "Naked 100 Pineapple Berry (Berry Lush) E-juice" -> [{{"flavor": "Pineapple Berry", "description": "Berry Lush"}}]
- "Oxbar Ice-Nic Control 35K Bananers" with "Flavors: Banana, Peach, Tropical" -> [{{"flavor": "Bananers", "description": "Banana, peach, tropical"}}]
- "Pod Juice Banana Ice / Banana Freeze" -> [{{"flavor": "Banana Ice / Banana Freeze", "description": "ripe banana with menthol"}}]
- "VUSE Alto Pods" with "Aqua Frost Menthol - desc. Dusk Glow Tobacco - desc. Golden Spark Tobacco - desc. Golden Tobacco - desc. Menthol - desc."
  Step 1: No flavor in Product Name, look in Description
  Step 2: Count = 5 flavors (look for "Name -" pattern)
  Step 3: Extract all 5: Aqua Frost Menthol, Dusk Glow Tobacco, Golden Spark Tobacco, Golden Tobacco, Menthol
  Result: [{{"flavor": "Aqua Frost Menthol", ...}}, {{"flavor": "Dusk Glow Tobacco", ...}}, {{"flavor": "Golden Spark Tobacco", ...}}, {{"flavor": "Golden Tobacco", ...}}, {{"flavor": "Menthol", ...}}]

Examples of INCORRECT extraction:
- "Strawberry Kiwi Pomberry" -> [{{"flavor": "Strawberry"}}, {{"flavor": "Kiwi"}}, {{"flavor": "Pomberry"}}] WRONG - keep as ONE
- "Blue Razz Ice" -> [{{"flavor": "Blue"}}, {{"flavor": "Razz"}}, {{"flavor": "Ice"}}] WRONG - keep as ONE
- "Pod Juice Salt Jewel Tobacco" -> [{{"flavor": "Tobacco"}}] WRONG - include Jewel as part of flavor name and extract Jewel Tobacco
- "Vapetasia Killer Kustard Blueberry" -> [{{"flavor": "Blueberry"}}] WRONG - use flavor name from product name Killer Kustard Blueberry

Rules for the "description" field:
- Extract ONLY the actual flavor profile (ingredients, taste notes, flavor combinations) from Description/Flavor Text
- Do NOT copy the flavor name into description
- Keep descriptions short (under 50 characters if possible)
- Use null if no taste information is available

Return ONLY a valid JSON array with NO extra text:
[{{"flavor": "complete flavor name", "description": "taste notes or null"}}]

If no flavor is found (e.g. hardware product), return: []

JSON output:"""


def get_flavor_extraction_status(
    parsed: List[Dict]
) -> str:
    if not parsed:
        return "no_flavors_found"

    if len(parsed) == 1:
        return "one_flavor_found"

    return "multiple_flavors"


def process_flavor_extraction_row(
    row: Dict,
    retry_count: int = 0
) -> Dict:
    result = {
        "id": row.get("id", ""),
        "unique_id": normalize_unique_id(
            row.get("unique_id", "")
        ),
        "product_name": clean_value(
            row.get("product_name", "")
        ),
        "site_name": clean_value(
            row.get("site_name", "")
        ),
        "url": clean_value(
            row.get("url", "")
        ),
        "site_category": clean_value(
            row.get("site_category", "")
        ),
        "flavor_text": clean_value(
            row.get("flavor_text", "")
        ),
        "description": clean_value(
            row.get("description", "")
        )
    }

    try:
        response = client.chat.completions.create(
            model=FLAVOR_EXTRACTION_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a precise data extraction assistant. "
                        "Output only valid JSON arrays."
                    )
                },
                {
                    "role": "user",
                    "content": build_flavor_extraction_prompt(row)
                }
            ],
            temperature=0.0,
            max_tokens=3000
        )

        raw_output = clean_text(
            response.choices[0].message.content or ""
        ).strip()

        parsed = clean_flavor_json_string(raw_output)

        if parsed is None:
            if retry_count < MAX_RETRIES:
                time.sleep(
                    RETRY_DELAY * (retry_count + 1)
                )
                return process_flavor_extraction_row(
                    row,
                    retry_count + 1
                )

            result.update({
                "extracted_data": "[]",
                "extraction_status": "json_error",
                "raw_llm_response": raw_output
            })
            return result

        result.update({
            "extracted_data": json.dumps(
                parsed,
                ensure_ascii=True
            ),
            "extraction_status": get_flavor_extraction_status(
                parsed
            ),
            "raw_llm_response": ""
        })

        return result

    except Exception as exc:
        if retry_count < MAX_RETRIES:
            time.sleep(
                RETRY_DELAY * (retry_count + 1)
            )
            return process_flavor_extraction_row(
                row,
                retry_count + 1
            )

        logger.exception(
            "Flavor extraction failed for product_id=%s.",
            row.get("id")
        )

        result.update({
            "extracted_data": "[]",
            "extraction_status": "json_error",
            "raw_llm_response": f"API ERROR: {exc}"
        })

        return result


def run_flavor_extraction(
    source_df: pd.DataFrame
) -> pd.DataFrame:
    if source_df.empty:
        return pd.DataFrame()

    records = source_df.to_dict("records")
    results = [None] * len(records)
    success_count = 0
    error_count = 0

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:
        futures = {
            executor.submit(
                process_flavor_extraction_row,
                record
            ): index
            for index, record in enumerate(records)
        }

        progress = tqdm(
            as_completed(futures),
            total=len(futures),
            desc="Extracting flavor attributes",
            unit="product",
            dynamic_ncols=True
        )

        for future in progress:
            index = futures[future]
            row = records[index]

            try:
                result = future.result()

            except Exception as exc:
                logger.exception(
                    "Unexpected flavor extraction failure "
                    "for product_id=%s.",
                    row.get("id")
                )

                result = {
                    **row,
                    "extracted_data": "[]",
                    "extraction_status": "json_error",
                    "raw_llm_response": (
                        f"UNEXPECTED ERROR: {exc}"
                    )
                }

            results[index] = result

            if result.get("extraction_status") == "json_error":
                error_count += 1
            else:
                success_count += 1

            progress.set_postfix({
                "ok": success_count,
                "err": error_count
            })

        progress.close()

    extraction_df = sort_by_product_id(
        pd.DataFrame(results)
    )

    write_jsonl_checkpoint(
        extraction_df.to_dict("records"),
        FLAVOR_CHECKPOINT_FILE
    )

    logger.info(
        "Flavor extraction complete. ok=%s, err=%s.",
        success_count,
        error_count
    )

    return extraction_df


def parse_flavor_extracted_data(
    value
) -> List[Dict]:
    if value is None:
        return []

    if isinstance(value, list):
        return value

    text = str(value).strip()

    if not text or text == "[]":
        return []

    try:
        parsed = json.loads(text)

        if isinstance(parsed, list):
            return parsed

    except json.JSONDecodeError:
        pass

    try:
        parsed = ast.literal_eval(text)

        if isinstance(parsed, list):
            return parsed

    except (ValueError, SyntaxError):
        pass

    return []


def flatten_flavor_extraction_results(
    extraction_df: pd.DataFrame
) -> pd.DataFrame:
    if extraction_df.empty:
        return pd.DataFrame()

    flattened_rows = []

    for _, row in tqdm(
        extraction_df.iterrows(),
        total=len(extraction_df),
        desc="Flattening extraction results",
        unit="product",
        dynamic_ncols=True
    ):
        base_row = row.to_dict()
        flavors = parse_flavor_extracted_data(
            row.get("extracted_data", "[]")
        )

        valid_flavors = [
            item
            for item in flavors
            if isinstance(item, dict)
            and clean_value(
                item.get("flavor", "")
            ).strip()
        ]

        if not valid_flavors:
            output_row = base_row.copy()
            output_row["flavor"] = ""
            output_row["flavor_description"] = ""
            flattened_rows.append(output_row)
            continue

        for item in valid_flavors:
            output_row = base_row.copy()
            output_row["flavor"] = clean_value(
                item.get("flavor", "")
            ).strip()
            output_row["flavor_description"] = clean_value(
                item.get("description", "")
            ).strip()
            flattened_rows.append(output_row)

    return sort_by_product_id(
        pd.DataFrame(flattened_rows)
    )


# ============================================================================
# ORIGINAL FLAVOR CLASSIFICATION PROMPT
# ============================================================================

def create_flavor_category_prompt(
    flavor: str,
    flavor_description: str = ""
) -> str:
    return f"""
You are a precise vape flavor classifier. Assign exactly ONE category and, if applicable, one subcategory to the product below.

        ## Categories
        - CLEAR/OTHER COOLING: marketed as unflavored but contains coolants. (e.g., "Clear", "Frozen Tundra", "Arctic", "Clear Emerald", "Clear Blue", Clear Pink").
        - TOBACCO: tobacco-only or tobacco + menthol/cooling additive (e.g., "Tobacco Ice", "Classic Tobacco"). Tobacco is the main flavor, but can include hints of sweet, honey, or spice notes (e.g. "AMERICAN PATRIOT", "TURKISH TOBACCO", "TRIBECA").
        - MINT: Use only when the name or description explicitly contains mint, spearmint, peppermint, or wintergreen. Mint plus menthol/cooling remains MINT.
        - MENTHOL: Use for menthol, ice, icy, freeze, glacier, or cooling-only flavors with no explicit mint, spearmint, peppermint, or wintergreen. Plain "Menthol" is always MENTHOL.
        - UNFLAVOURED: explicitly no flavor and no cooling (e.g. "Naked", "Unflavored", "Original"). "Clear" does not count as unflavored.
        - OTHER FLAVORS: ANY of the following like fruit, dessert, candy, beverage, multi-flavor mix, tobacco + non-menthol additive, OR any mint variant that is NOT a pure mint (e.g. "mint chip", "black mint", "black menthol", "black ice")
        - OTHER FLAVORS: Also use Other Flavors when the name is a completely abstract non-flavor word (e.g., a person's name, a city name alone) and no description is available

        ## Subcategory Logic (ONLY for "Other Flavors")
        If you assign the category "Other Flavors", you must also assign exactly one of the following subcategories:
        - Sweets: Desserts, Candy, Bakery, Breakfast, Chocolate. (PRIORITY: 'Sweets' overrides all other subcategories if a prepared food/candy identifier is present, such as Bakery items ("Muffin", "Pie"), spreads ("Jam", "Jelly"), or candy terms ("Pop", "Gush", "Gum", "Drop", "Skit"). 
        - Alcoholic Beverages: Margaritas, mojitos, coladas, beer, wine, and other alcoholic cocktail drinks.
        - Coffee/Tea: Coffee, Tea, and related drinks including "Cafe", "Mocha", "Frappe", and "Latte".
        - Other Beverages: Soda, soft drinks, energy drinks (e.g. "Energize"), and non-fruit slushies (e.g., "Cola Slushy", "Baja Slushy").
        - Fruit: Pure fruit flavors, fruit blends (including mixed berry), fruit juices, lemonades, and fruit punches (e.g. "Tropical Fruit Punch"), and fruit-based slushies 
        - Mint Blends: Hybrid flavors that contain mint in the product name along with another element (e.g., Fruit + Mint like "Miami Mint", Chocolate + Mint).
        - Miscellaneous: Use for any flavor containing "Tobacco" (unless it is Coffee/Tea Tobacco), abstract flavor names, complex mixes that don't fit elsewhere, or when the name is ambiguous and the description is unclear.
        
        ## Critical Rules (apply in order)
        0. **If the flavor name matches an explicit example above, always assign that exact category first—even if the description is ambiguous.**
        1. **Description Overrides Name**: If a description is provided, it is the primary signal for BOTH the Main Category and the Subcategory.
        2. **Default to Other Flavors, not Unknown.** If the name sounds like a flavor variant or is an invented flavor name (even abstract like "Meta Moon", "Cosmic Blast", "Fcuking Fab", "Love Story"), classify as **OTHER FLAVORS**. Reserve **UNKNOWN** only for names that give zero flavor signal.
        3. **Default to Mint if the word "mint" is in the name AND there is no description (e.g. "Jewel Mint", "Miami Mint")
        4. **Default to Clear only if the word "clear" is in the name.
        5. **Tobacco + menthol/ice -> Tobacco. Tobacco + fruit/vanilla/caramel/coffee (e.g. "Tobacco Cream", "Tobbaco coffee", "Tobaccoccino") -> **OTHER FLAVORS**. 
        6. **Fruit + any cooling -> Other Flavors** (e.g. "Black Ice/Icy" means it is dark fruit or candy flavored, "Lush Ice", "Mango Freeze", "Frozen Lush", "Stone Freeze", "Summer Glacier", "Skit Ice").
        7. **Ambiguity Rule:** If the flavor name is ambiguous (e.g. "Black Ice", "Blue Dream", "Lush", "Rainbow") and the description is blank or does not specify a subcategory, assign the subcategory **'Miscellaneous'**.

## Output
Return ONLY a valid JSON object:
{{
    "flavor_category": "<CATEGORY IN ALL CAPS>",
    "category_rationale": "<short reason for main category>",
    "subcategory": "<subcategory_if_other_else_null>",
    "subcategory_rationale": "<short reason for subcategory, or null if not Other Flavors>",
    "concept_flavor": "T" | "F",
    "concept_rationale": "<one sentence explaining which words make it concept or why it's explicit>"
}}

## Product
- Flavor Name: "{flavor}"
- Flavor Description: "{flavor_description}"

JSON output:
"""


def normalize_flavor_type(
    value
) -> str:
    value = clean_value(value).strip().lower()

    if value in {"t", "true", "concept"}:
        return "concept"

    if value in {"f", "false", "explicit"}:
        return "explicit"

    return ""


def is_flavor_classification_error(
    row
) -> bool:
    return clean_value(
        row.get("flavor_type_rationale", "")
    ).strip().startswith("ERROR:")

def get_flavor_classification_error_message(
    row
) -> str:
    return clean_value(
        row.get("flavor_type_rationale", "")
    ).strip()

def classify_flavor(
    flavor: str,
    flavor_description: str = "",
    retry_count: int = 0
) -> Dict:
    last_error = ""

    for attempt in range(MAX_RETRIES + 1):
        try:
            if RATE_LIMIT_DELAY > 0:
                time.sleep(RATE_LIMIT_DELAY)

            response = client.chat.completions.create(
                model=FLAVOR_CLASSIFICATION_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a precise vape flavor classifier "
                            "assistant. Output only valid compact JSON "
                            "as specified."
                        )
                    },
                    {
                        "role": "user",
                        "content": create_flavor_category_prompt(
                            flavor,
                            flavor_description
                        )
                    }
                ],
                temperature=0.0,
                max_tokens=1000
            )

            text = clean_value(
                response.choices[0].message.content or ""
            ).strip()

            text = re.sub(
                r"^```(?:json)?\s*",
                "",
                text,
                flags=re.IGNORECASE
            )
            text = re.sub(
                r"\s*```$",
                "",
                text
            ).strip()

            try:
                result = json.loads(text)
            except json.JSONDecodeError as exc:
                raw_preview = text[:2000]
                raise ValueError(
                    f"Invalid classification JSON: {exc}. "
                    f"Raw response: {raw_preview}"
                ) from exc

            if not isinstance(result, dict):
                raise ValueError(
                    "Classification response was not a JSON object"
                )

            return {
                "flavor_category": clean_value(
                    result.get("flavor_category", "")
                ).upper(),
                "flavor_category_rationale": clean_value(
                    result.get("category_rationale", "")
                ),
                "flavor_subcategory": clean_value(
                    result.get("subcategory", "")
                ),
                "flavor_subcategory_rationale": clean_value(
                    result.get("subcategory_rationale", "")
                ),
                "flavor_type": normalize_flavor_type(
                    result.get("concept_flavor", "")
                ),
                "flavor_type_rationale": clean_value(
                    result.get("concept_rationale", "")
                )
            }

        except Exception as exc:
            last_error = str(exc)

            if attempt < MAX_RETRIES:
                logger.warning(
                    "Classification retry %s/%s for flavor=%s: %s",
                    attempt + 1,
                    MAX_RETRIES,
                    flavor,
                    exc
                )

                time.sleep(
                    RETRY_DELAY * (attempt + 1)
                )

    logger.error(
        "Classification failed after %s attempts for flavor=%s: %s",
        MAX_RETRIES + 1,
        flavor,
        last_error
    )

    return {
        "flavor_category": "",
        "flavor_category_rationale": "",
        "flavor_subcategory": "",
        "flavor_subcategory_rationale": "",
        "flavor_type": "",
        "flavor_type_rationale": f"ERROR: {last_error}"
    }


def run_flavor_classification(
    flattened_df: pd.DataFrame
) -> pd.DataFrame:
    if flattened_df.empty:
        return pd.DataFrame()

    records = flattened_df.to_dict("records")
    results = [None] * len(records)
    unique_inputs = {}
    futures = {}

    for index, record in enumerate(records):
        flavor = clean_value(
            record.get("flavor", "")
        ).strip()

        if not flavor:
            results[index] = {
                "flavor_category": "",
                "flavor_category_rationale": "",
                "flavor_subcategory": "",
                "flavor_subcategory_rationale": "",
                "flavor_type": "",
                "flavor_type_rationale": ""
            }
            continue

        description = clean_value(
            record.get("flavor_description", "")
        ).strip()

        unique_inputs.setdefault(
            (flavor, description),
            []
        ).append(index)

    logger.info(
        "Classifying %s rows using %s unique flavor inputs.",
        len(records),
        len(unique_inputs)
    )

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:
        for flavor, description in unique_inputs:
            futures[
                executor.submit(
                    classify_flavor,
                    flavor,
                    description
                )
            ] = (flavor, description)

        for future in tqdm(
            as_completed(futures),
            total=len(futures),
            desc="Classifying flavors",
            unit="unique flavor",
            dynamic_ncols=True
        ):
            result = future.result()
            key = futures[future]

            for index in unique_inputs[key]:
                results[index] = result.copy()

    classified_df = pd.concat(
        [
            flattened_df.reset_index(drop=True),
            pd.DataFrame(results).reset_index(drop=True)
        ],
        axis=1
    )

    return sort_by_product_id(classified_df)


# ============================================================================
# FLAVOR SQL
# ============================================================================

FLAVOR_INSERT_SQL = f"""
INSERT INTO {FLAVOR_OUTPUT_TABLE}
(
    product_id,
    unique_id,
    flavor,
    flavor_description,
    flavor_category,
    flavor_subcategory,
    flavor_type,
    date_inserted,
    date_updated
)
SELECT
    ?, ?, ?, ?, ?, ?, ?,
    SYSUTCDATETIME(),
    NULL
WHERE NOT EXISTS
(
    SELECT 1
    FROM {FLAVOR_OUTPUT_TABLE}
        WITH (UPDLOCK, HOLDLOCK)
    WHERE product_id = ?
      AND unique_id = ?
      AND flavor = ?
)
"""


def prefer_flavor_database_values(current, new):
    merged = current.copy()

    for field in [
        "flavor_description",
        "flavor_category",
        "flavor_subcategory",
        "flavor_type"
    ]:
        current_value = clean_value(
            current.get(field, "")
        ).strip()

        new_value = clean_value(
            new.get(field, "")
        ).strip()

        merged[field] = new_value or current_value

    return merged


def get_flavor_database_values(row):
    return {
        "flavor_description": clean_value(
            row.get("flavor_description", "")
        ),
        "flavor_category": clean_value(
            row.get("flavor_category", "")
        ).upper(),
        "flavor_subcategory": clean_value(
            row.get("flavor_subcategory", "")
        ).upper(),
        "flavor_type": clean_value(
            row.get("flavor_type", "")
        ).upper()
    }


def insert_flavor_attributes(
    classified_df: pd.DataFrame
):
    if classified_df.empty:
        logger.info("No flavor attributes to save.")
        return

    working_df = classified_df.copy()

    # Extraction failures are never eligible for insertion.
    if "extraction_status" in working_df.columns:
        working_df = working_df[
            working_df["extraction_status"]
            != "json_error"
        ].copy()

    if working_df.empty:
        logger.info(
            "No valid flavor attributes to save."
        )
        return

    # Identify all product/unique_id pairs where at least one flavor
    # classification failed.
    #
    # Do not insert ANY flavor for those pairs. Otherwise, a successful
    # flavor from the same product would mark that product pair as complete,
    # and the failed flavor would never be retried on the next run.
    failed_pair_keys = {
        (
            clean_value(row.get("id", "")).strip(),
            normalize_unique_id(row.get("unique_id", ""))
        )
        for _, row in working_df.iterrows()
        if is_flavor_classification_error(row)
    }

    if failed_pair_keys:
        logger.warning(
            "Deferring insertion for %s product pair(s) because at "
            "least one flavor classification failed. These pairs will "
            "be retried on the next run.",
            len(failed_pair_keys)
        )

        working_df = working_df[
            ~working_df.apply(
                lambda row: (
                    clean_value(row.get("id", "")).strip(),
                    normalize_unique_id(row.get("unique_id", ""))
                ) in failed_pair_keys,
                axis=1
            )
        ].copy()

    # Defensive removal of individual failed rows as well.
    working_df = working_df[
        ~working_df.apply(
            is_flavor_classification_error,
            axis=1
        )
    ].copy()

    if working_df.empty:
        logger.info(
            "No valid flavor attributes to save after excluding "
            "classification-error product pairs."
        )
        return

    classified_df = uppercase_database_values(
        working_df,
        [
            "flavor",
            "flavor_category",
            "flavor_subcategory",
            "flavor_type"
        ]
    )

    candidate_rows = {}

    for _, row in tqdm(
        classified_df.iterrows(),
        total=len(classified_df),
        desc="Preparing flavor SQL inserts",
        unit="row",
        dynamic_ncols=True
    ):
        product_id_text = required_value(
            row.get("id", "")
        )

        if product_id_text is None:
            continue

        product_id = int(float(product_id_text))
        unique_id = normalize_unique_id(
            row.get("unique_id", "")
        )
        flavor = clean_value(
            row.get("flavor", "")
        ).strip().upper()

        key = (
            product_id,
            unique_id,
            flavor
        )

        values = get_flavor_database_values(row)

        if key in candidate_rows:
            candidate_rows[key] = (
                prefer_flavor_database_values(
                    candidate_rows[key],
                    values
                )
            )
        else:
            candidate_rows[key] = values

    if not candidate_rows:
        logger.info(
            "No valid flavor candidates to insert."
        )
        return

    insert_rows = []

    for key, values in candidate_rows.items():
        product_id, unique_id, flavor = key

        insert_rows.append(
            (
                product_id,
                unique_id,
                flavor,
                values["flavor_description"],
                values["flavor_category"],
                values["flavor_subcategory"],
                values["flavor_type"],
                product_id,
                unique_id,
                flavor
            )
        )

    conn = get_db_connection()

    try:
        cursor = conn.cursor()
        cursor.fast_executemany = True

        for start in tqdm(
            range(0, len(insert_rows), BATCH_SIZE),
            desc="Inserting flavor SQL batches",
            unit="batch",
            dynamic_ncols=True
        ):
            batch = insert_rows[start:start + BATCH_SIZE]

            if batch:
                cursor.executemany(
                    FLAVOR_INSERT_SQL,
                    batch
                )
                conn.commit()

        logger.info(
            "Flavor SQL complete. Candidates=%s.",
            len(candidate_rows)
        )

    except Exception:
        conn.rollback()
        logger.exception(
            "Flavor SQL insert failed."
        )
        raise

    finally:
        conn.close()


# ============================================================================
# MODEL SOURCE LOADING
# ============================================================================

def load_model_products_for_processing() -> pd.DataFrame:
    rows_to_process = (
        MODEL_TEST_ROWS
        if TEST_MODE
        else PROCESS_BATCH_SIZE
    )

    query = f"""
    SELECT TOP {rows_to_process}
        p.id,
        p.unique_id,
        p.product_name,
        p.brand,
        p.site_name,
        p.site_tag,
        p.description
    FROM {INPUT_TABLE} AS p
    WHERE p.id IS NOT NULL
      AND p.product_name IS NOT NULL
      AND NOT EXISTS
      (
          SELECT 1
          FROM {MODEL_OUTPUT_TABLE} AS ma
          WHERE ma.product_id = p.id
            AND ISNULL(ma.unique_id, '') =
                ISNULL(p.unique_id, '')
      )
    ORDER BY
        p.id ASC,
        ISNULL(p.unique_id, '') ASC
    """

    conn = get_db_connection()

    try:
        df = pd.read_sql_query(query, conn)
    finally:
        conn.close()

    df = df.fillna("")
    df["unique_id"] = df["unique_id"].apply(
        normalize_unique_id
    )

    logger.info(
        "Loaded %s rows for model attributes. TEST_ROWS=%s",
        len(df),
        MODEL_TEST_ROWS if TEST_MODE else "disabled"
    )

    return df


# ============================================================================
# MODEL EXTRACTION
# ============================================================================

BRAND_EXTRACTION_PROMPT = """
You are a vape product analyst. Extract the brand name and product line from the listing below.

**brand_name**: The manufacturer/company name (e.g., "FLUM", "Geek Bar", "7 Daze").
**product_line**: The named series/model family within the brand (e.g., "PEBBLE", "Pulse", "Clickmate"). Null if none.

Rules:
- brand_name must contain the full brand only. Never place a product line, flavor, puff count, nicotine %, size, version, or generic product type in brand_name.
- If the listing says "Brand A x Brand B", brand_name must contain both collaborators exactly as "Brand A X Brand B". Do not return only Brand A. The pipeline will later split "Brand A X Brand B" into primary Brand A and collaborating brand Brand B.
- Product line typically follows the brand name, before specs (puff counts, nicotine %, sizes) or generic words ("Disposable", "Vape", "Device", "Kit", "Pod").
- Use Existing Brand and Site Tags only as supporting context; product name and description are the primary signal.

Examples:
"FLUM PEBBLE 6000 Puff Disposable" -> {{"brand_name": "FLUM", "product_line": "PEBBLE"}}
"Geek Bar Pulse 15000 Puff Disposable" -> {{"brand_name": "Geek Bar", "product_line": "Pulse"}}
"Cigi Plus 3000 Puff Disposable Device" -> {{"brand_name": "Cigi", "product_line": "Plus"}}
"Lost Mary MO20000 Pro Disposable" -> {{"brand_name": "Lost Mary", "product_line": "MO20000 Pro"}}
"7 Daze Clickmate 15k Puff Disposable Kit" -> {{"brand_name": "7 Daze", "product_line": "Clickmate"}}
"Juice Head 30k Puff Disposable" -> {{"brand_name": "Juice Head", "product_line": null}}
"Cuttwood x Cali Bar 5% Disposable Device" -> {{"brand_name": "CUTTWOOD X CALI BAR", "product_line": null}}


Product Name: "{product_name}"
Description: "{description}"
Existing Brand: "{brand}"
Site Tags: "{site_tag}"

Respond with ONLY a valid JSON object: {{"brand_name": "...", "product_line": "..."}}
"""


def parse_brand_json(
    response_text
) -> Dict:
    text = clean_value(response_text).strip()

    text = re.sub(
        r"^```(?:json)?\s*",
        "",
        text,
        flags=re.IGNORECASE
    )
    text = re.sub(
        r"\s*```$",
        "",
        text
    ).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid model extraction JSON: {exc}. "
            f"Raw response: {text[:2000]}"
        ) from exc

    if not isinstance(data, dict):
        raise ValueError(
            "Model extraction response was not a JSON object. "
            f"Raw response: {text[:2000]}"
        )

    brand_name = clean_optional(
        data.get("brand_name", "")
    )

    if not brand_name:
        return {
            "status": "no_brand_found",
            "brand_name": "",
            "product_line": "",
            "rationale": "No identifiable manufacturer.",
            "raw_llm_response": text
        }

    return {
        "model_status": "success",
        "brand_name": brand_name,
        "product_line": clean_optional(
            data.get("product_line", "")
        ),
        "rationale": clean_value(
            data.get("rationale", "")
        ),
        "raw_llm_response": text
    }


def extract_model_brand(
    row,
    retry_count: int = 0
) -> Dict:
    prompt = BRAND_EXTRACTION_PROMPT.format(
        product_name=clean_value(
            row.get("product_name", "")
        ),
        description=clean_value(
            row.get("description", "")
        ),
        brand=clean_value(
            row.get("brand", "")
        ),
        site_tag=clean_value(
            row.get("site_tag", "")
        )
    )

    raw_response = ""

    try:
        completion = client.chat.completions.create(
            model=MODEL_EXTRACTION_MODEL,
            temperature=0.0,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        raw_response = clean_value(
            completion.choices[0].message.content or ""
        ).strip()

        return parse_brand_json(raw_response)

    except Exception as exc:
        if retry_count < MAX_RETRIES:
            logger.warning(
                "Model extraction retry %s/%s for product_id=%s: %s",
                retry_count + 1,
                MAX_RETRIES,
                row.get("id"),
                exc
            )

            time.sleep(
                RETRY_DELAY * (retry_count + 1)
            )

            return extract_model_brand(
                row,
                retry_count + 1
            )

        logger.exception(
            "Model extraction failed after %s attempts for "
            "product_id=%s.",
            MAX_RETRIES + 1,
            row.get("id")
        )

        return {
            "model_status": "error",
            "brand_name": "",
            "product_line": "",
            "rationale": f"ERROR: {exc}",
            "raw_llm_response": raw_response
        }

def run_model_extraction(
    source_df: pd.DataFrame
) -> pd.DataFrame:
    if source_df.empty:
        return pd.DataFrame()

    records = source_df.to_dict("records")
    results = [None] * len(records)
    success_count = 0
    error_count = 0

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:
        futures = {
            executor.submit(
                extract_model_brand,
                row
            ): index
            for index, row in enumerate(records)
        }

        progress = tqdm(
            as_completed(futures),
            total=len(futures),
            desc="Extracting model attributes",
            unit="product",
            dynamic_ncols=True
        )

        for future in progress:
            index = futures[future]
            row = records[index]

            try:
                result = future.result()

            except Exception as exc:
                logger.exception(
                    "Unexpected model extraction failure "
                    "for product_id=%s.",
                    row.get("id")
                )

                result = {
                    "model_status": "error",
                    "brand_name": "",
                    "product_line": "",
                    "rationale": f"Unexpected error: {exc}",
                    "raw_llm_response": ""
                }

            # raw_llm_response is retained temporarily for the error CSV.
            # It is removed before the regular extraction CSV is written.
            results[index] = {
                "id": row.get("id", ""),
                "unique_id": normalize_unique_id(
                    row.get("unique_id", "")
                ),
                "product_name": clean_value(
                    row.get("product_name", "")
                ),
                "llm_brand_name": clean_optional(
                    result.get("brand_name", "")
                ),
                "llm_product_line": clean_optional(
                    result.get("product_line", "")
                ),
                "llm_rationale": clean_value(
                    result.get("rationale", "")
                ),
                "model_status": clean_value(
                    result.get("model_status", "error")
                ),
                "raw_llm_response": clean_value(
                    result.get("raw_llm_response", "")
                )
            }

            if result.get("model_status") == "success":
                success_count += 1
            elif result.get("model_status") == "error":
                error_count += 1

            progress.set_postfix({
                "ok": success_count,
                "err": error_count
            })

        progress.close()

        extraction_df = sort_by_product_id(
        pd.DataFrame(results)
    )

    model_error_df = extraction_df[
        extraction_df["model_status"] == "error"
    ].copy()

    if not model_error_df.empty:
        model_error_df["error_message"] = (
            model_error_df["llm_rationale"]
        )

        append_error_log(
            pipeline="model",
            stage="extraction",
            records=model_error_df.to_dict("records")
        )

        logger.warning(
            "Found %s model extraction error row(s). "
            "They will not be inserted and will retry on the next run.",
            len(model_error_df)
        )

    # Keep the regular brand extraction CSV at its intended six columns.
    extraction_output_df = extraction_df.drop(
        columns=["raw_llm_response"],
        errors="ignore"
    )

    append_csv_history(
        extraction_output_df,
        MODEL_EXTRACTION_OUTPUT_FILE
    )

    write_jsonl_checkpoint(
        extraction_output_df.to_dict("records"),
        MODEL_CHECKPOINT_FILE
    )

    logger.info(
        "Model extraction complete. ok=%s, err=%s.",
        success_count,
        error_count
    )

    return extraction_output_df


# ============================================================================
# MODEL RECONCILIATION
# ============================================================================


COMMON_BRAND_MAPPING = {
    "ELF BAR": "ELFBAR",
    "HYPPE BAR": "HYPPE",
    "POP VAPE": "POP",
    "BANGVAPES": "BANG",
    "MY BLU": "BLU",
    "VOODOO LABS": "VOODOO",
    "THE RIPPLE CO": "RIPPLE",
    "EMERALD VAPORS": "EMERALD",
    "RANDM": "R&M",
    "FULL SEND VAPOR": "FULL SEND",
    "BEARD VAPE CO": "BEARD VAPE",
    "POD JUICE": "POD JUICE",
    "JAM MONSTER": "PB AND JAM MONSTER"
}


def load_processed_model_rows() -> pd.DataFrame:
    query = f"""
    SELECT DISTINCT
        ma.product_id AS id,
        ISNULL(ma.unique_id, '') AS unique_id,
        p.product_name,
        ma.brand_full_name AS llm_brand_name,
        ma.product_line AS llm_product_line,
        '' AS llm_rationale
    FROM {MODEL_OUTPUT_TABLE} AS ma
    INNER JOIN {INPUT_TABLE} AS p
        ON p.id = ma.product_id
       AND ISNULL(p.unique_id, '') =
           ISNULL(ma.unique_id, '')
    WHERE ma.product_id IS NOT NULL
    """

    conn = get_db_connection()

    try:
        df = pd.read_sql_query(query, conn)
    finally:
        conn.close()

    return df.fillna("")


def most_common_value(series) -> str:
    values = [
        clean_optional(value)
        for value in series
        if clean_optional(value)
    ]

    return (
        Counter(values).most_common(1)[0][0]
        if values
        else ""
    )


def resolve_extracted_brand_lines(
    extraction_df: pd.DataFrame
) -> pd.DataFrame:
    df = extraction_df.copy().fillna("")

    df["llm_brand_name"] = df[
        "llm_brand_name"
    ].apply(clean_optional)

    df["llm_product_line"] = df[
        "llm_product_line"
    ].apply(clean_optional)

    df["brand_key"] = df[
        "llm_brand_name"
    ].map(normalize_key)

    df["line_key"] = df[
        "llm_product_line"
    ].map(normalize_key)

    brand_canon_map = {}

    for key, group in df[
        df["brand_key"] != ""
    ].groupby("brand_key"):
        brand_canon_map[key] = most_common_value(
            group["llm_brand_name"]
        )

    df["brand_canonical"] = (
        df["brand_key"]
        .map(brand_canon_map)
        .fillna("")
    )

    known_brands = set(
        df.loc[
            df["brand_key"] != "",
            "brand_key"
        ]
    )

    known_brand_line_pairs = set(
        zip(
            df.loc[
                (
                    df["brand_key"] != ""
                )
                & (
                    df["line_key"] != ""
                ),
                "brand_key"
            ],
            df.loc[
                (
                    df["brand_key"] != ""
                )
                & (
                    df["line_key"] != ""
                ),
                "line_key"
            ]
        )
    )

    def find_absorbed(
        brand_key: str
    ) -> Optional[Tuple[str, str]]:
        words = brand_key.split()

        if len(words) < 2:
            return None

        for split_at in range(1, len(words)):
            prefix = " ".join(words[:split_at])
            suffix = " ".join(words[split_at:])

            if (
                prefix in known_brands
                and (
                    prefix,
                    suffix
                ) in known_brand_line_pairs
            ):
                return prefix, suffix

        return None

    absorbed_corrections = {}

    for brand_key in known_brands:
        correction = find_absorbed(brand_key)

        if correction:
            absorbed_corrections[brand_key] = correction

    def resolve_brand_line(row):
        brand_key = row["brand_key"]

        if brand_key in absorbed_corrections:
            correct_brand_key, correct_line_key = (
                absorbed_corrections[brand_key]
            )

            resolved_brand = brand_canon_map.get(
                correct_brand_key,
                correct_brand_key
            )

            matching_lines = df.loc[
                (
                    df["brand_key"]
                    == correct_brand_key
                )
                & (
                    df["line_key"]
                    == correct_line_key
                ),
                "llm_product_line"
            ]

            resolved_line = (
                most_common_value(matching_lines)
                if not matching_lines.empty
                else correct_line_key.title()
            )

            return resolved_brand, resolved_line

        return (
            brand_canon_map.get(
                brand_key,
                row["llm_brand_name"]
            ),
            row["llm_product_line"]
        )

    resolved = df.apply(
        resolve_brand_line,
        axis=1,
        result_type="expand"
    )

    resolved.columns = [
        "brand_resolved",
        "line_resolved"
    ]

    df = pd.concat(
        [df, resolved],
        axis=1
    )

    df["brand_resolved_key"] = df[
        "brand_resolved"
    ].map(normalize_key)

    df["line_resolved_key"] = df[
        "line_resolved"
    ].map(normalize_key)

    line_canon_map = {}

    valid = df[
        (
            df["brand_resolved_key"] != ""
        )
        & (
            df["line_resolved_key"] != ""
        )
    ]

    for (
        brand_key,
        line_key
    ), group in valid.groupby(
        [
            "brand_resolved_key",
            "line_resolved_key"
        ]
    ):
        line_canon_map[
            (brand_key, line_key)
        ] = most_common_value(
            group["line_resolved"]
        )

    df["line_canonical"] = df.apply(
        lambda row: line_canon_map.get(
            (
                row["brand_resolved_key"],
                row["line_resolved_key"]
            ),
            row["line_resolved"]
        ),
        axis=1
    )

    return df

BRAND_PRODUCT_SUFFIX_PATTERNS = [
    r"\s+E[- ]LIQUIDS?$",
    r"\s+ELIQUIDS?$",
    r"\s+E[- ]JUICES?$",
    r"\s+EJUICES?$",
    r"\s+VAPE\s+SALTS?$",
    r"\s+VAPOR\s+SALTS?$",
    r"\s+SALTS?$",
    r"\s+VAPES?$"
]


def normalize_brand_surface(
    value: str
) -> str:
    value = clean_value(
        value
    ).strip().upper()

    value = re.sub(
        r"\s*,\s*",
        ", ",
        value
    )

    value = re.sub(
        r"\s+",
        " ",
        value
    ).strip()

    return value


def remove_brand_product_suffix(
    value: str
) -> str:
    """
    Removes product-type suffixes from brand_name only.

    The complete value remains in brand_full_name.
    """
    result = normalize_brand_surface(
        value
    )

    for pattern in BRAND_PRODUCT_SUFFIX_PATTERNS:
        result = re.sub(
            pattern,
            "",
            result,
            flags=re.IGNORECASE
        ).strip()

    return result.strip(" ,")


def canonical_common_brand_name(
    value: str
) -> str:
    value = remove_brand_product_suffix(
        value
    )

    # Make punctuation variants consistent:
    # CLIC, BANG -> CLIC BANG
    value = re.sub(
        r"\s*,\s*",
        " ",
        value
    )

    value = re.sub(
        r"\s+",
        " ",
        value
    ).strip()

    return COMMON_BRAND_MAPPING.get(
        value,
        value
    )

def normalize_brand_product_line(
    row
):
    brand_full_name = normalize_brand_surface(
        row.get("brand_canonical", "")
    )

    product_line = clean_value(
        row.get("line_canonical", "")
    ).strip().upper()

    if not brand_full_name:
        return pd.Series({
            "brand_full_name": "",
            "brand_name": "",
            "collab_brand_name": "",
            "product_line": ""
        })

    # Only X is a collaboration delimiter.
    # AND is intentionally not split.
    collaboration_match = re.match(
        r"^(.+?)\s+X\s+(.+)$",
        brand_full_name,
        flags=re.IGNORECASE
    )

    if collaboration_match:
        first_brand = collaboration_match.group(
            1
        ).strip()

        second_brand = collaboration_match.group(
            2
        ).strip()

        return pd.Series({
            "brand_full_name": (
                f"{first_brand} X {second_brand}"
            ).upper(),

            "brand_name": canonical_common_brand_name(
                first_brand
            ),

            "collab_brand_name": canonical_common_brand_name(
                second_brand
            ),

            "product_line": product_line
        })

    # AND remains inside brand_full_name and is not a collaboration.
    return pd.Series({
        "brand_full_name": brand_full_name,

        "brand_name": canonical_common_brand_name(
            brand_full_name
        ),

        "collab_brand_name": "",

        "product_line": product_line
    })

def build_resolved_model_dataframe(
    extraction_df: pd.DataFrame
) -> pd.DataFrame:
    if extraction_df.empty:
        return pd.DataFrame()

    resolved_df = resolve_extracted_brand_lines(
        extraction_df
    )

    normalized_df = resolved_df.apply(
        normalize_brand_product_line,
        axis=1
    )

    final_df = pd.concat(
        [
            resolved_df.reset_index(drop=True),
            normalized_df.reset_index(drop=True)
        ],
        axis=1
    )

    return uppercase_database_values(
        final_df,
        [
            "brand_full_name",
            "brand_name",
            "collab_brand_name",
            "product_line"
        ]
    )


def build_brand_line_map(
    resolved_df: pd.DataFrame
) -> pd.DataFrame:
    if resolved_df.empty:
        return pd.DataFrame()

    valid_df = resolved_df[
        resolved_df["brand_name"]
        .fillna("")
        .astype(str)
        .str.strip()
        != ""
    ]

    if valid_df.empty:
        return pd.DataFrame()

    result = (
        valid_df
        .groupby(
            [
                "brand_name",
                "product_line"
            ],
            dropna=False
        )
        .agg(
            product_count=("id", "count")
        )
        .reset_index()
        .sort_values(
            [
                "brand_name",
                "product_count"
            ],
            ascending=[True, False]
        )
        .reset_index(drop=True)
    )

    result["has_product_line"] = (
        result["product_line"]
        .fillna("")
        .astype(str)
        .str.strip()
        != ""
    )

    return result


# ============================================================================
# MODEL SQL
# ============================================================================

MODEL_INSERT_SQL = f"""
INSERT INTO {MODEL_OUTPUT_TABLE}
(
    product_id,
    unique_id,
    brand_full_name,
    brand_name,
    collab_brand_name,
    product_line,
    date_inserted,
    date_updated
)
SELECT
    ?, ?, ?, ?, ?, ?,
    SYSUTCDATETIME(),
    NULL
WHERE NOT EXISTS
(
    SELECT 1
    FROM {MODEL_OUTPUT_TABLE}
        WITH (UPDLOCK, HOLDLOCK)
    WHERE product_id = ?
      AND ISNULL(unique_id, '') = ?
)
"""


def get_model_database_values(row):
    return {
        "brand_full_name": clean_value(
            row.get("brand_full_name", "")
        ).upper(),
        "brand_name": clean_value(
            row.get("brand_name", "")
        ).upper(),
        "collab_brand_name": clean_value(
            row.get("collab_brand_name", "")
        ).upper(),
        "product_line": clean_value(
            row.get("product_line", "")
        ).upper()
    }


def merge_model_batch_values(current, new):
    merged = current.copy()

    for column in [
        "brand_full_name",
        "brand_name",
        "collab_brand_name",
        "product_line"
    ]:
        merged[column] = (
            clean_value(new.get(column, ""))
            or clean_value(current.get(column, ""))
        )

    return merged


def insert_model_attributes(
    final_df: pd.DataFrame
):
    if final_df.empty:
        logger.info("No model attributes to save.")
        return

    # Insert normal successful extractions and valid terminal no-brand rows.
    # Do not insert true technical failures; those must retry next run.
    if "model_status" in final_df.columns:
        final_df = final_df[
            final_df["model_status"].isin(
                ["success", "no_brand_found"]
            )
        ].copy()
    else:
        # Retain existing defensive behavior if older data has no status.
        final_df = final_df[
            final_df["brand_name"]
            .fillna("")
            .astype(str)
            .str.strip()
            != ""
        ].copy()

    if final_df.empty:
        logger.info(
            "No valid model attributes to save."
        )
        return

    final_df = uppercase_database_values(
        final_df,
        [
            "brand_full_name",
            "brand_name",
            "collab_brand_name",
            "product_line"
        ]
    )

    candidate_rows = {}

    for _, row in tqdm(
        final_df.iterrows(),
        total=len(final_df),
        desc="Preparing model SQL inserts",
        unit="row",
        dynamic_ncols=True
    ):
        product_id_text = required_value(
            row.get("id", "")
        )

        if product_id_text is None:
            continue

        product_id = int(float(product_id_text))
        unique_id = normalize_unique_id(
            row.get("unique_id", "")
        )

        values = get_model_database_values(row)

        key = (
            product_id,
            unique_id
        )

        if key in candidate_rows:
            candidate_rows[key] = (
                merge_model_batch_values(
                    candidate_rows[key],
                    values
                )
            )
        else:
            candidate_rows[key] = values

    if not candidate_rows:
        logger.info(
            "No valid model candidates to insert."
        )
        return

    insert_rows = []

    for (
        product_id,
        unique_id
    ), values in candidate_rows.items():
        insert_rows.append(
            (
                product_id,
                unique_id,
                values["brand_full_name"],
                values["brand_name"],
                values["collab_brand_name"],
                values["product_line"],
                product_id,
                unique_id
            )
        )

    conn = get_db_connection()

    try:
        cursor = conn.cursor()
        cursor.fast_executemany = True

        for start in tqdm(
            range(0, len(insert_rows), BATCH_SIZE),
            desc="Inserting model SQL batches",
            unit="batch",
            dynamic_ncols=True
        ):
            batch = insert_rows[
                start:start + BATCH_SIZE
            ]

            if batch:
                cursor.executemany(
                    MODEL_INSERT_SQL,
                    batch
                )
                conn.commit()

        logger.info(
            "Model SQL complete. Candidates=%s.",
            len(candidate_rows)
        )

    except Exception:
        conn.rollback()
        logger.exception(
            "Model SQL insert failed."
        )
        raise

    finally:
        conn.close()


# ============================================================================
# METRICS
# ============================================================================

def write_flavor_metrics(
    source_df,
    extraction_df,
    flattened_df,
    classified_df
):
    rows_with_flavors = 0

    if "flavor" in classified_df.columns:
        rows_with_flavors = int(
            (
                classified_df["flavor"]
                .fillna("")
                .astype(str)
                .str.strip()
                != ""
            ).sum()
        )

    status_counts = {}

    if "extraction_status" in extraction_df.columns:
        status_counts = (
            extraction_df["extraction_status"]
            .value_counts()
            .to_dict()
        )

    metrics = {
        "run_timestamp_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "test_mode": TEST_MODE,
        "flavor_test_rows": FLAVOR_TEST_ROWS,
        "source_rows_loaded": len(source_df),
        "extraction_rows": len(extraction_df),
        "flattened_rows": len(flattened_df),
        "classified_rows": len(classified_df),
        "rows_with_flavors": rows_with_flavors,
        "rows_without_flavors": (
            len(classified_df) - rows_with_flavors
        ),
        "extraction_status_counts": status_counts
    }

    with open(
        FLAVOR_METRICS_FILE,
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            metrics,
            file,
            indent=2,
            default=str
        )


def write_model_metrics(
    source_df,
    extraction_df,
    final_df
):
    rows_with_brand = 0
    rows_with_product_line = 0

    if "brand_name" in final_df.columns:
        rows_with_brand = int(
            (
                final_df["brand_name"]
                .fillna("")
                .astype(str)
                .str.strip()
                != ""
            ).sum()
        )

    if "product_line" in final_df.columns:
        rows_with_product_line = int(
            (
                final_df["product_line"]
                .fillna("")
                .astype(str)
                .str.strip()
                != ""
            ).sum()
        )

    metrics = {
        "run_timestamp_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "test_mode": TEST_MODE,
        "model_test_rows": MODEL_TEST_ROWS,
        "source_rows_loaded": len(source_df),
        "extraction_rows": len(extraction_df),
        "final_rows": len(final_df),
        "max_workers": MAX_WORKERS,
        "rows_with_brand": rows_with_brand,
        "rows_with_product_line": rows_with_product_line
    }

    with open(
        MODEL_METRICS_FILE,
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            metrics,
            file,
            indent=2,
            default=str
        )


# ============================================================================
# PIPELINE RUNNERS
# ============================================================================

def run_flavor_pipeline(
    source_df: pd.DataFrame
) -> int:
    if source_df.empty:
        logger.info(
            "No flavor attributes require processing."
        )
        return 0

    extraction_df = run_flavor_extraction(
        source_df
    )

    if extraction_df.empty:
        return len(source_df)

    append_csv_history(
        extraction_df,
        FLAVOR_EXTRACTION_OUTPUT_FILE
    )

    extraction_error_count = int(
        (
            extraction_df["extraction_status"]
            == "json_error"
        ).sum()
    )

    extraction_error_df = extraction_df[
        extraction_df["extraction_status"]
        == "json_error"
    ].copy()

    if not extraction_error_df.empty:
        extraction_error_df["error_message"] = (
            extraction_error_df["raw_llm_response"]
        )

        append_error_log(
            pipeline="flavor",
            stage="extraction",
            records=extraction_error_df.to_dict("records")
        )

    if extraction_error_count:
        logger.warning(
            "Skipping %s flavor extraction-error rows. "
            "They will be retried on the next run.",
            extraction_error_count
        )

    valid_extraction_df = extraction_df[
        extraction_df["extraction_status"]
        != "json_error"
    ].copy()

    if valid_extraction_df.empty:
        logger.info(
            "All flavor extraction rows failed. "
            "No flavor rows will be inserted."
        )
        return len(source_df)

    flattened_df = flatten_flavor_extraction_results(
        valid_extraction_df
    )

    if flattened_df.empty:
        return len(source_df)

    append_csv_history(
        flattened_df,
        FLAVOR_FLATTENED_OUTPUT_FILE
    )

    classified_df = run_flavor_classification(
        flattened_df
    )

    classification_error_df = classified_df[
        classified_df.apply(
            is_flavor_classification_error,
            axis=1
        )
    ].copy()

    if not classification_error_df.empty:
        classification_error_df["error_message"] = (
            classification_error_df.apply(
                get_flavor_classification_error_message,
                axis=1
            )
        )

        append_error_log(
            pipeline="flavor",
            stage="classification",
            records=classification_error_df.to_dict("records")
        )

        logger.warning(
            "Found %s flavor classification error row(s). "
            "Their product pairs will not be inserted and will retry "
            "on the next pipeline run.",
            len(classification_error_df)
        )

    if classified_df.empty:
        return len(source_df)

    classified_df = uppercase_database_values(
        classified_df,
        [
            "flavor",
            "flavor_category",
            "flavor_subcategory",
            "flavor_type"
        ]
    )

    append_csv_history(
        classified_df,
        FLAVOR_CLASSIFIED_OUTPUT_FILE
    )

    insert_flavor_attributes(
        classified_df
    )

    write_flavor_metrics(
        source_df,
        extraction_df,
        flattened_df,
        classified_df
    )

    return len(source_df)


def load_processed_model_rows() -> pd.DataFrame:
    query = f"""
    SELECT DISTINCT
        ma.product_id AS id,
        ISNULL(ma.unique_id, '') AS unique_id,
        p.product_name,
        ma.brand_full_name AS llm_brand_name,
        ma.product_line AS llm_product_line,
        '' AS llm_rationale
    FROM {MODEL_OUTPUT_TABLE} AS ma
    INNER JOIN {INPUT_TABLE} AS p
        ON p.id = ma.product_id
       AND ISNULL(p.unique_id, '') =
           ISNULL(ma.unique_id, '')
    WHERE ma.product_id IS NOT NULL
    """

    conn = get_db_connection()

    try:
        df = pd.read_sql_query(query, conn)
    finally:
        conn.close()

    return df.fillna("")


def run_model_pipeline(
    source_df: pd.DataFrame
) -> int:
    if source_df.empty:
        logger.info(
            "No model attributes require processing."
        )
        return 0

    extraction_df = run_model_extraction(
        source_df
    )
    
    # Only successful extractions and valid no-brand outcomes are complete.
    # True technical errors are not inserted and will retry next run.
    completed_extraction_df = extraction_df[
        extraction_df["model_status"].isin(
            ["success", "no_brand_found"]
        )
    ].copy()

    if completed_extraction_df.empty:
        logger.info(
            "No completed model extraction rows to reconcile."
        )
        return len(source_df)
    
    processed_model_df = load_processed_model_rows()

    if processed_model_df.empty:
        reconciliation_df = completed_extraction_df.copy()
    else:
        reconciliation_df = pd.concat(
            [
                processed_model_df,
                completed_extraction_df
            ],
            ignore_index=True,
            sort=False
        ).fillna("")

    resolved_all_df = build_resolved_model_dataframe(
        reconciliation_df
    )

    if resolved_all_df.empty:
        return len(source_df)

    current_keys = {
        (
            clean_value(
                row.get("id", "")
            ).strip(),
            normalize_unique_id(
                row.get("unique_id", "")
            )
        )
        for _, row in source_df.iterrows()
    }

    current_df = resolved_all_df[
        resolved_all_df.apply(
            lambda row: (
                clean_value(
                    row.get("id", "")
                ).strip(),
                normalize_unique_id(
                    row.get("unique_id", "")
                )
            ) in current_keys,
            axis=1
        )
    ].copy()

    current_df = current_df.drop_duplicates(
        subset=["id", "unique_id"],
        keep="last"
    )

    current_df = sort_by_product_id(
        current_df
    )

    append_csv_history(
        current_df,
        MODEL_RESOLVED_OUTPUT_FILE
    )

    append_csv_history(
        current_df,
        MODEL_FINAL_OUTPUT_FILE
    )

    brand_line_map = build_brand_line_map(
        resolved_all_df
    )

    if not brand_line_map.empty:
        brand_line_map.to_csv(
            MODEL_BRAND_LINE_MAP_FILE,
            index=False
        )

    insert_model_attributes(
        current_df
    )

    write_model_metrics(
        source_df,
        extraction_df,
        current_df
    )

    return len(source_df)


# ============================================================================
# UNIFIED MAIN
# ============================================================================

def main():
    start_time = time.time()

    # Start a fresh error log for this pipeline run.
    if os.path.exists(ERROR_LOG_FILE):
        os.remove(ERROR_LOG_FILE)

    logger.info(
        "STARTING FEATURE EXTRACTION PIPELINE"
    )

    logger.info(
        "TEST_MODE=%s | FLAVOR_TEST_ROWS=%s | "
        "MODEL_TEST_ROWS=%s | MAX_WORKERS=%s",
        TEST_MODE,
        FLAVOR_TEST_ROWS,
        MODEL_TEST_ROWS,
        MAX_WORKERS
    )

    print_pipeline_counts()

    flavor_source_df = load_flavor_products_for_processing()
    model_source_df = load_model_products_for_processing()

    processed_product_keys = set()

    for source_df in [
        flavor_source_df,
        model_source_df
    ]:
        if source_df.empty:
            continue

        for _, row in source_df.iterrows():
            processed_product_keys.add(
                (
                    clean_value(
                        row.get("id", "")
                    ).strip(),
                    normalize_unique_id(
                        row.get("unique_id", "")
                    )
                )
            )

    processed_product_count = len(
        processed_product_keys
    )

    if processed_product_count == 0:
        logger.info(
            "No new product_id + unique_id pairs "
            "found for either pipeline."
        )
        return

    with ThreadPoolExecutor(
        max_workers=2
    ) as executor:
        futures = {}

        if not flavor_source_df.empty:
            futures[
                executor.submit(
                    run_flavor_pipeline,
                    flavor_source_df
                )
            ] = "flavor"

        if not model_source_df.empty:
            futures[
                executor.submit(
                    run_model_pipeline,
                    model_source_df
                )
            ] = "model"

        for future in as_completed(futures):
            pipeline_name = futures[future]

            try:
                future.result()

                logger.info(
                    "%s attribute pipeline finished.",
                    pipeline_name.capitalize()
                )

            except Exception:
                logger.exception(
                    "%s attribute pipeline failed.",
                    pipeline_name.capitalize()
                )
                raise

    elapsed_seconds = time.time() - start_time
    elapsed_minutes = elapsed_seconds / 60

    products_per_second = (
        processed_product_count / elapsed_seconds
        if elapsed_seconds > 0
        else 0
    )

    logger.info(
        "Feature Extraction Pipeline completed in "
        "%.2f minutes, %.1f products/sec.",
        elapsed_minutes,
        products_per_second
    )


if __name__ == "__main__":
    main()