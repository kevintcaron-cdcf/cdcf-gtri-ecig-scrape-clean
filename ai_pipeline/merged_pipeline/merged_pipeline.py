"""
merged_pipeline.py

MERGED two-stage E-cigarette product pipeline for SLURM array jobs.

Base: Old Prompt pipeline (old_product_classify.py) - kept for its Disposable System
and combination-device strength. Merged in from the Current Prompt, as CODE rather than
prompt text wherever possible:
  * policy_rules.py       deterministic post-classification rules (R1-R9), which never
                          demote a Disposable System except for 510 / e-nail / dab-tool
  * CBD guard             a CBD-filter positive with no cannabinoid term in the text is
                          sent on to classification (fixes brand/name-guess positives)
  * CBD rationale         the CBD filter's own rationale is now written to `rationale`
  * merged_prompts.py     the Old prompt with targeted edits E1-E7

Stage 1 (filter): CBD detection. If is_cbd == True (and the guard agrees) ->
                  category := "CBD", skip stage 2.
Stage 2 (classify): full product classification, then policy_rules.apply_category_policy.

One model load serves both stages. Each array task processes one contiguous
slice of the input CSV.
"""
import os
import sys
from contextlib import contextmanager
from pathlib import Path


def load_local_env(env_path):
    """Load simple KEY=VALUE entries from a local, Git-ignored env file.

    Existing environment variables take precedence so cluster/job settings are
    not overwritten by the local file.
    """
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        os.environ.setdefault(name, value)

# Make sibling modules (merged_prompts.py, policy_rules.py) importable no matter which
# directory the SLURM job cds into before launching python.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load credentials from a same-directory file. ``langfuse_env.txt`` is used as
# the default because some JupyterLab cluster deployments reject dotfiles.
# The file is Git-ignored; credentials are never stored in this source file.
langfuse_env_path = os.environ.get("LANGFUSE_ENV_FILE")
if langfuse_env_path:
    load_local_env(Path(langfuse_env_path).expanduser())
else:
    for candidate in ("langfuse_env.txt", ".env"):
        candidate_path = Path(__file__).with_name(candidate)
        if candidate_path.is_file():
            load_local_env(candidate_path)
            break

os.environ["LANGFUSE_HOST"] = os.environ.get(
    "LANGFUSE_HOST", "https://langfuse.dev.heat.icl.gtri.org"
)
os.environ.setdefault("LANGFUSE_TIMEOUT", "5")

missing_langfuse_vars = [
    name
    for name in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")
    if not os.environ.get(name)
]
if missing_langfuse_vars:
    raise RuntimeError(
        "Missing required Langfuse environment variables: "
        + ", ".join(missing_langfuse_vars)
        + ". Set them in the environment or in a local langfuse_env.txt file."
    )

import argparse
import json
import re
import time
import gc
from datetime import datetime, timedelta

import pandas as pd
import torch
from transformers import Qwen3VLMoeForConditionalGeneration, AutoProcessor

from langfuse import get_client

try:
    from langfuse import propagate_attributes as _legacy_propagate_attributes
except ImportError:
    _legacy_propagate_attributes = None

langfuse_client = get_client()


@contextmanager
def propagate_attributes(tags=None, metadata=None):
    """Apply trace attributes across supported Langfuse client versions.

    Langfuse 2 provides a top-level helper; Langfuse 3 exposes this functionality
    through update_current_trace instead.
    """
    if _legacy_propagate_attributes is not None:
        with _legacy_propagate_attributes(tags=tags, metadata=metadata):
            yield
    else:
        langfuse_client.update_current_trace(tags=tags, metadata=metadata)
        yield

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser()
parser.add_argument("--input", required=True)
parser.add_argument("--image_dir", required=True)
parser.add_argument("--model_dir", required=True)
parser.add_argument("--output", default=None)
parser.add_argument("--max_items", type=int, default=None)
parser.add_argument("--cbd_max_tokens", type=int, default=400)
parser.add_argument("--cls_max_tokens", type=int, default=250)
parser.add_argument("--checkpoint_interval", type=int, default=25)
parser.add_argument("--chunk_id", type=int, default=None,
                    help="Process only this chunk (0-indexed)")
parser.add_argument("--total_chunks", type=int, default=None,
                    help="Total number of chunks")
parser.add_argument("--cbd_error_policy", choices=["classify", "skip"],
                    default="classify",
                    help="When CBD stage returns is_cbd is None (parse/runtime "
                         "error): 'classify' runs stage 2; 'skip' marks Error.")
parser.add_argument("--debug_token_accounting", action="store_true")
parser.add_argument("--assert_token_crosscheck", action="store_true")
parser.add_argument("--disable_policy_rules", action="store_true",
                    help="Skip policy_rules.apply_category_policy (raw model output only; "
                         "pre_override_category is still recorded).")
parser.add_argument("--disable_cbd_guard", action="store_true",
                    help="Trust every CBD-filter positive, even with no cannabinoid term "
                         "in the listing text.")
args = parser.parse_args()

if args.output is None:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    args.output = f"results/merged_pipeline_{timestamp}.csv"
Path(args.output).parent.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Prompts + deterministic policy rules
# ---------------------------------------------------------------------------
from merged_prompts import (  # noqa: E402  (prompts live in their own module)
    CBD_DETECTION_PROMPT,
    PRODUCT_CATEGORIES,
    CATS_DESCRIPTION,
    BASE_PROMPT,
)
import policy_rules  # noqa: E402

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def find_image_path(image_dir, site_name, site_tag):
    if not site_name or not site_tag:
        return None
    folder = Path(image_dir) / f"{site_name}_images"
    if not folder.exists():
        return None
    # create_image_collages.py writes one product-level collage in this location.
    # Prefer it so the VLM receives all available product views as one image input.
    p = folder / f"{site_tag}_collage.jpg"
    if p.exists():
        return str(p)
    for ext in [".jpg", ".jpeg", ".png", ".webp"]:
        p = folder / f"{site_tag}{ext}"
        if p.exists():
            return str(p)
    for ext in [".jpg", ".jpeg", ".png", ".webp"]:
        p = folder / f"{site_tag}_1{ext}"
        if p.exists():
            return str(p)
    # No prefix glob: "{site_tag}*" matched other products whose tag starts with this one
    # (e.g. "smok-novo-2-pods" -> "smok-novo-2-pods-0-8-mesh_collage.jpg").
    return None


def format_time(seconds):
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}m"
    else:
        return f"{seconds/3600:.1f}h"


# ---------------------------------------------------------------------------
# JSON extraction (shared regex core, field-specific parsers)
# ---------------------------------------------------------------------------
def _strip_fences(text):
    return re.sub(r"```(?:json)?", "", text).strip().strip("`").strip()


def extract_json_generic(text, field):
    text = _strip_fences(text)
    m = re.search(r'\{(?:[^{}]|(?:\{[^{}]*\}))*\}', text, re.DOTALL)
    if m:
        return m.group(0)
    m = re.search(r'\{[^{}]*"' + field + r'"[^{}]*\}', text, re.DOTALL)
    if m:
        return m.group(0)
    m = re.search(r'\{[^{}]*"' + field + r'"[^{}]*', text, re.DOTALL)
    if m:
        jt = m.group(0)
        if jt.count('"') % 2 == 1:
            jt += '"'
        if not jt.rstrip().endswith('}'):
            jt += '}'
        return jt
    return text


def extract_cls_json(text):
    """Extract a complete classifier JSON object without repairing truncation."""
    text = _strip_fences(text)
    match = re.search(r'\{(?:[^{}]|(?:\{[^{}]*\}))*\}', text, re.DOTALL)
    return match.group(0) if match else text


def parse_cbd_json(text, original_text=None):
    json_text = extract_json_generic(text, "is_cbd")
    try:
        data = json.loads(json_text)
        is_cbd = data.get("is_cbd")
        if is_cbd is None:
            raise ValueError("Missing is_cbd field")
        rationale = data.get("rationale", "").lower()
        cbd_keywords = [
            "cbd", "thc", "cannabis", "hemp", "delta-8", "delta-9",
            "concentrate", "dab", "wax", "terpene", "cannabinoid",
            "hhc", "510-thread",
        ]
        indicators = [kw for kw in cbd_keywords if kw in rationale]
        return {
            "is_cbd": bool(is_cbd),
            "cbd_confidence": data.get("confidence", "unknown"),
            "cbd_rationale": data.get("rationale", "")[:1000],
            "cbd_indicators": ", ".join(indicators),
            "cbd_raw_response": "",
        }
    except (json.JSONDecodeError, ValueError) as e:
        return {
            "is_cbd": None,
            "cbd_confidence": "error",
            "cbd_rationale": f"Parse error: {str(e)[:100]}",
            "cbd_indicators": "",
            "cbd_raw_response": (original_text or text)[:500],
        }


def _coerce_bool(value, default=False):
    """Convert common model boolean representations to a stable Python bool."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1"}:
            return True
        if normalized in {"false", "no", "0"}:
            return False
    return default


def _text_or_none(value, max_length=500):
    if value is None:
        return None
    value = str(value).strip()
    return value[:max_length] if value else None


def parse_cls_json(text, original_text=None):
    try:
        # Do not auto-close a truncated classifier response. It must remain an
        # Error with raw_response retained, and must not cause a no-image retry.
        json_text = extract_cls_json(text)
        data = json.loads(json_text)
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object")
        category = data.get("categories")
        if not isinstance(category, str) or not category.strip():
            raise ValueError("Missing categories field")
        rationale = data.get("rationale", "")
        if rationale is None:
            rationale = ""
        return {
            "categories": category,
            "confidence": data.get("confidence", "low"),
            "rationale": str(rationale)[:1000],
            "combination_device": _coerce_bool(data.get("combination_device")),
            "combination_device_rationale": _text_or_none(
                data.get("combination_device_rationale")
            ),
            "raw_response": "",
        }
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError) as e:
        return {
            "categories": "Error",
            "confidence": "low",
            "rationale": f"Parse error: {str(e)[:100]}",
            "combination_device": False,
            "combination_device_rationale": None,
            "raw_response": (original_text or text)[:500],
        }


# ---------------------------------------------------------------------------
# Token accounting (classification stage)
# ---------------------------------------------------------------------------
def resolve_image_token_id(model, processor):
    tid = getattr(model.config, "image_token_id", None)
    if tid is None:
        tid = processor.tokenizer.convert_tokens_to_ids("<|image_pad|>")
    if tid is None or tid < 0:
        raise ValueError("Could not resolve image_token_id.")
    return int(tid)


def count_image_placeholder_tokens(inputs, image_token_id):
    return int((inputs["input_ids"] == image_token_id).sum())


def count_vision_patch_tokens(inputs):
    if "image_grid_thw" not in inputs:
        return 0
    return sum(int(t) * int(h) * int(w) for t, h, w in inputs["image_grid_thw"].tolist())


def get_precise_token_counts(inputs, outputs, has_image, image_token_id, merge_size):
    serialized_input_tokens = int(inputs["input_ids"].shape[-1])
    image_placeholder_tokens = (
        count_image_placeholder_tokens(inputs, image_token_id) if has_image else 0
    )
    non_image_input_tokens = serialized_input_tokens - image_placeholder_tokens
    vision_patch_tokens = count_vision_patch_tokens(inputs) if has_image else 0
    vision_merged_tokens = (
        vision_patch_tokens // (merge_size * merge_size) if has_image else 0
    )
    completion_tokens = int(outputs.shape[-1] - inputs["input_ids"].shape[-1])
    total_tokens = serialized_input_tokens + completion_tokens
    counts = {
        "image_placeholder_tokens": image_placeholder_tokens,
        "non_image_input_tokens": non_image_input_tokens,
        "serialized_input_tokens": serialized_input_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "vision_patch_tokens": vision_patch_tokens,
        "vision_merged_tokens": vision_merged_tokens,
    }
    if has_image and args.assert_token_crosscheck:
        assert vision_merged_tokens == image_placeholder_tokens, (
            f"Token mismatch: placeholders={image_placeholder_tokens} "
            f"vision_merged={vision_merged_tokens}."
        )
    return counts


# ---------------------------------------------------------------------------
# Inference primitives
# ---------------------------------------------------------------------------
def build_messages(prompt, image_path=None):
    content = []
    if image_path:
        content.append({"type": "image", "image": image_path})
    content.append({"type": "text", "text": prompt})
    return [{"role": "user", "content": content}]


def run_generation(model, processor, prompt, image_path, max_tokens):
    """Shared generate call. Returns (response_text, inputs, outputs)."""
    messages = build_messages(prompt, image_path=image_path)
    inputs = processor.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        return_dict=True,
        return_tensors="pt",
    ).to(model.device)
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=max_tokens,
            do_sample=False,
            pad_token_id=processor.tokenizer.eos_token_id,
        )
    response = processor.batch_decode(
        [outputs[0][inputs["input_ids"].shape[-1]:]],
        skip_special_tokens=True,
    )[0]
    return response, inputs, outputs


# ---------------------------------------------------------------------------
# Stage 1: CBD detection
# ---------------------------------------------------------------------------
def call_vlm_cbd(model, processor, prompt, image_path, generation_name):
    gen_start = time.time()
    with langfuse_client.start_as_current_observation(
        name=generation_name,
        as_type="generation",
        model=args.model_dir.split("/")[-1],
        input=prompt,
        metadata={
            "has_image": image_path is not None,
            "image_path": image_path or "",
            "max_tokens": args.cbd_max_tokens,
            "stage": "cbd_filter",
        },
    ) as generation:
        response, inputs, outputs = run_generation(
            model, processor, prompt, image_path, args.cbd_max_tokens
        )
        prompt_tokens = int(inputs["input_ids"].shape[-1])
        completion_tokens = int(outputs.shape[-1] - inputs["input_ids"].shape[-1])
        total_tokens = prompt_tokens + completion_tokens
        parsed = parse_cbd_json(response, original_text=response)
        generation.update(
            output=response,
            usage_details={
                "input": prompt_tokens,
                "output": completion_tokens,
                "total": total_tokens,
            },
            metadata={
                "inference_time_seconds": time.time() - gen_start,
                "parsed_is_cbd": parsed.get("is_cbd"),
                "parsed_confidence": parsed.get("cbd_confidence"),
            },
        )
    del inputs, outputs
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return parsed


def detect_cbd(row, model, processor, image_dir, item_num):
    image_path = find_image_path(image_dir, row.get("site_name"), row.get("site_tag"))
    prompt = CBD_DETECTION_PROMPT.format(
        product_name=row.get("product_name", ""),
        site_category=row.get("site_category", ""),
        site_tag=row.get("site_tag", ""),
        description=row.get("description", ""),
        package_contents=row.get("eliquid_contents", ""),
    )
    with langfuse_client.start_as_current_observation(
        name=f"cbd_detection_item_{item_num}", as_type="span"
    ) as trace_span:
        with propagate_attributes(
            tags=["cbd_detection", "qwen3-vl", "slurm"],
            metadata={
                "item_number": item_num,
                "product_name": row.get("product_name", ""),
                "site_name": row.get("site_name", ""),
                "site_tag": row.get("site_tag", ""),
                "site_category": row.get("site_category", ""),
                "has_image": image_path is not None,
            },
        ):
            result = call_vlm_cbd(model, processor, prompt, image_path,
                                  "cbd_initial_detection")
            if image_path and result["is_cbd"] is None:
                result = call_vlm_cbd(model, processor, prompt, None,
                                      "cbd_retry_without_image")
                result["cbd_retry_without_image"] = True
            else:
                result["cbd_retry_without_image"] = False
            result["image_path"] = image_path or ""
            result["has_image"] = image_path is not None
            trace_span.update(output={
                "is_cbd": result["is_cbd"],
                "confidence": result["cbd_confidence"],
                "rationale": result["cbd_rationale"],
                "indicators": result["cbd_indicators"],
            })
    return result, image_path


# ---------------------------------------------------------------------------
# Stage 2: Product classification
# ---------------------------------------------------------------------------
def call_vlm_cls(model, processor, prompt, image_path, generation_name):
    gen_start = time.time()
    with langfuse_client.start_as_current_observation(
        name=generation_name,
        as_type="generation",
        model=args.model_dir.split("/")[-1],
        input=prompt,
        metadata={
            "has_image": image_path is not None,
            "image_path": image_path or "",
            "max_tokens": args.cls_max_tokens,
            "stage": "classification",
        },
    ) as generation:
        response, inputs, outputs = run_generation(
            model, processor, prompt, image_path, args.cls_max_tokens
        )
        gen_elapsed = time.time() - gen_start
        parsed = parse_cls_json(response, original_text=response)
        tc = get_precise_token_counts(
            inputs=inputs,
            outputs=outputs,
            has_image=(image_path is not None),
            image_token_id=IMAGE_TOKEN_ID,
            merge_size=MERGE_SIZE,
        )
        if args.debug_token_accounting:
            print(
                f"[TOKEN DEBUG] {generation_name} | has_image={image_path is not None} | "
                f"img_placeholder={tc['image_placeholder_tokens']} | "
                f"non_image={tc['non_image_input_tokens']} | "
                f"serialized={tc['serialized_input_tokens']} | "
                f"vision_patch={tc['vision_patch_tokens']} | "
                f"vision_merged={tc['vision_merged_tokens']} | "
                f"completion={tc['completion_tokens']} | total={tc['total_tokens']}"
            )
        generation.update(
            output=response,
            usage_details={
                "input_image": tc["image_placeholder_tokens"],
                "input_text": tc["non_image_input_tokens"],
                "output": tc["completion_tokens"],
                "total": tc["total_tokens"],
            },
            metadata={
                "inference_time_seconds": gen_elapsed,
                "parsed_category": parsed.get("categories"),
                "parsed_confidence": parsed.get("confidence"),
                "parsed_combination_device": parsed.get("combination_device"),
                "image_placeholder_tokens": tc["image_placeholder_tokens"],
                "non_image_input_tokens": tc["non_image_input_tokens"],
                "serialized_input_tokens": tc["serialized_input_tokens"],
                "completion_tokens": tc["completion_tokens"],
                "total_tokens": tc["total_tokens"],
                "vision_patch_tokens": tc["vision_patch_tokens"],
                "vision_merged_tokens": tc["vision_merged_tokens"],
                "has_image": image_path is not None,
                "num_images": 1 if image_path else 0,
            },
        )
    for k in ("image_placeholder_tokens", "non_image_input_tokens",
              "serialized_input_tokens", "completion_tokens", "total_tokens",
              "vision_patch_tokens", "vision_merged_tokens"):
        parsed[k] = tc[k]
    parsed["inference_time_seconds"] = gen_elapsed
    del inputs, outputs
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return parsed


def classify_product(row, model, processor, image_path, item_num):
    prompt = BASE_PROMPT.format(
        cats=CATS_DESCRIPTION,
        product_name=row.get("product_name", ""),
        site_category=row.get("site_category", ""),
        site_tag=row.get("site_tag", ""),
        description=row.get("description", ""),
        package_contents=row.get("eliquid_contents", ""),
    )
    with langfuse_client.start_as_current_observation(
        name=f"product_classification_item_{item_num}", as_type="span"
    ) as trace_span:
        with propagate_attributes(
            tags=["product_classification", "qwen3-vl", "slurm"],
            metadata={
                "item_number": item_num,
                "product_name": row.get("product_name", ""),
                "site_name": row.get("site_name", ""),
                "site_tag": row.get("site_tag", ""),
                "site_category": row.get("site_category", ""),
                "has_image": image_path is not None,
            },
        ):
            result = call_vlm_cls(model, processor, prompt, image_path,
                                  "cls_initial_classification")
            if image_path and result["categories"] in ("Other", "Unknown"):
                result = call_vlm_cls(model, processor, prompt, None,
                                      "cls_retry_without_image")
                result["cls_retry_without_image"] = True
            else:
                result["cls_retry_without_image"] = False

            # Deterministic policy layer (policy_rules.py). Runs after the retry so the
            # final model answer is the one validated. The model's own answer is kept
            # in pre_override_category / model_rationale for offline auditing.
            if result["categories"] != "Error":
                if args.disable_policy_rules:
                    result["categories"] = policy_rules.normalize_category(
                        result["categories"])
                    result["pre_override_category"] = result["categories"]
                    result["post_override_category"] = result["categories"]
                    result["model_rationale"] = result.get("rationale", "")
                    policy_rules.finalize_combination_flag(result, row)
                else:
                    result = policy_rules.apply_category_policy(result, row)

            trace_span.update(output={
                "category": result["categories"],
                "confidence": result["confidence"],
                "rationale": result["rationale"],
                "combination_device": result.get("combination_device"),
                "pre_override_category": result.get("pre_override_category"),
                "policy_rule_id": result.get("policy_rule_id"),
                "policy_override_reason": result.get("policy_override_reason"),
                "combo_rule_applied": result.get("combo_rule_applied"),
            })
    return result


# ---------------------------------------------------------------------------
# Result assembly helpers (guarantee stable CSV schema)
# ---------------------------------------------------------------------------
CLS_FIELD_DEFAULTS = {
    "categories": "",
    "confidence": "",
    "rationale": "",
    "model_rationale": "",
    "combination_device": False,
    "combination_device_rationale": None,
    "model_combination_device": False,
    "combo_rule_applied": None,
    "combo_component": False,
    "pre_override_category": "",
    "post_override_category": "",
    "policy_override_applied": False,
    "policy_rule_id": None,
    "policy_override_reason": None,
    "raw_response": "",
    "image_placeholder_tokens": 0,
    "non_image_input_tokens": 0,
    "serialized_input_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
    "vision_patch_tokens": 0,
    "vision_merged_tokens": 0,
    "inference_time_seconds": 0.0,
    "cls_retry_without_image": False,
}


def empty_cls_result(category, confidence, rationale):
    r = dict(CLS_FIELD_DEFAULTS)
    r["categories"] = category
    r["confidence"] = confidence
    r["rationale"] = rationale
    r["model_rationale"] = rationale
    r["pre_override_category"] = category
    r["post_override_category"] = category
    return r


def classify_product_safely(row, model, processor, image_path, item_num):
    """Return a stable error row so one classification failure does not stop the job."""
    try:
        return classify_product(row, model, processor, image_path, item_num)
    except Exception as e:
        error_message = f"Classification runtime error: {type(e).__name__}: {str(e)[:200]}"
        print(f"  -> Item {item_num} {error_message}")
        return empty_cls_result(
            category="Error",
            confidence="low",
            rationale=error_message,
        )


# ---------------------------------------------------------------------------
# Load model once
# ---------------------------------------------------------------------------
def main():
    global IMAGE_TOKEN_ID, MERGE_SIZE, PATCH_SIZE
    print(f"Loading model from {args.model_dir} ...")
    model_load_start = time.time()
    processor = AutoProcessor.from_pretrained(args.model_dir)
    model = Qwen3VLMoeForConditionalGeneration.from_pretrained(
        args.model_dir,
        torch_dtype=torch.bfloat16,
        device_map="auto",
    )
    model.eval()
    model_load_time = time.time() - model_load_start
    print(f"Model loaded in {format_time(model_load_time)}")
    print("Visible GPUs:", torch.cuda.device_count())
    print("Device map:", model.hf_device_map)

    IMAGE_TOKEN_ID = resolve_image_token_id(model, processor)
    MERGE_SIZE = getattr(processor.image_processor, "merge_size", 2)
    PATCH_SIZE = getattr(processor.image_processor, "patch_size", None)
    print(f"Resolved image_token_id={IMAGE_TOKEN_ID}, "
          f"merge_size={MERGE_SIZE}, patch_size={PATCH_SIZE}")

    # -----------------------------------------------------------------------
    # Load + chunk slice
    # -----------------------------------------------------------------------
    df = pd.read_csv(args.input)
    # Fail loudly if the input export is wrong, instead of silently sending blank prompts.
    required_input_cols = ["orig_id", "product_name", "site_name", "site_category",
                           "site_tag", "description", "eliquid_contents"]
    missing_cols = [c for c in required_input_cols if c not in df.columns]
    if missing_cols:
        raise SystemExit(f"--input is missing required columns: {missing_cols}")
    total_items = len(df)
    if args.chunk_id is not None and args.total_chunks is not None:
        chunk_size = (total_items + args.total_chunks - 1) // args.total_chunks
        start_idx = args.chunk_id * chunk_size
        end_idx = min((args.chunk_id + 1) * chunk_size, total_items)
        df = df.iloc[start_idx:end_idx].reset_index(drop=True)
        print(f"Processing chunk {args.chunk_id + 1}/{args.total_chunks}: "
        f"rows {start_idx}-{end_idx} ({len(df)} items)")
    else:
        print(f"No chunking specified; processing all {total_items} items")

    if args.max_items:
        df = df.head(args.max_items)
    print(f"Loaded {len(df)} products from {args.input}\n")

    # -----------------------------------------------------------------------
    # Combined loop
    # -----------------------------------------------------------------------
    results = []
    cbd_positive = 0
    cbd_errors = 0
    cls_success = 0
    cls_errors = 0
    classified_count = 0
    combination_device_count = 0
    cbd_guard_count = 0
    policy_override_count = 0
    item_times = []
    start_time = time.time()

    print("=" * 70)
    print(f"Starting MERGED pipeline at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"CBD max_tokens={args.cbd_max_tokens} | CLS max_tokens={args.cls_max_tokens} | "
          f"cbd_error_policy={args.cbd_error_policy} | "
          f"policy_rules={'OFF' if args.disable_policy_rules else 'ON'} | "
          f"cbd_guard={'OFF' if args.disable_cbd_guard else 'ON'}")
    print("=" * 70 + "\n")

    for i, (_, row) in enumerate(df.iterrows()):
        item_start = time.time()
        item_num = i + 1

        # ---- Stage 1: CBD filter ----
        try:
            cbd_result, image_path = detect_cbd(row, model, processor,
                                                args.image_dir, item_num)
        except Exception as e:
            cbd_result = {
                "is_cbd": None, "cbd_confidence": "error",
                "cbd_rationale": f"Runtime error: {str(e)[:200]}",
                "cbd_indicators": "", "cbd_raw_response": "",
                "image_path": "", "has_image": False,
                "cbd_retry_without_image": False,
            }
            image_path = None

        is_cbd = cbd_result["is_cbd"]

        # ---- CBD guard (merged pipeline) ----
        # A CBD-filter positive with no cannabinoid term anywhere in the listing text is a
        # brand/name guess (e.g. "Cali XLT 40K", "Cosmic Fog Kryptonite"); classify it.
        cbd_result["cbd_guard_applied"] = False
        if (is_cbd is True and not args.disable_cbd_guard
                and policy_rules.cbd_guard_should_override(row)):
            cbd_result["cbd_guard_applied"] = True
            cbd_guard_count += 1
            is_cbd = False

        # ---- Routing ----
        if is_cbd is True:
            cbd_positive += 1
            cls_result = empty_cls_result(
                category="CBD",
                confidence=cbd_result["cbd_confidence"],
                # Surface the CBD filter's own reasoning in the output / HTML review.
                rationale=(cbd_result.get("cbd_rationale")
                           or "Routed by CBD filter (stage 1)."),
            )
            stage = "cbd_filter"
        elif is_cbd is False:
            classified_count += 1
            cls_result = classify_product_safely(
                row, model, processor, image_path, item_num
            )
            if cls_result["categories"] == "Error":
                cls_errors += 1
            else:
                cls_success += 1
            stage = ("classified_after_cbd_guard" if cbd_result["cbd_guard_applied"]
                     else "classified")
        else:  # is_cbd is None -> filter error
            cbd_errors += 1
            if args.cbd_error_policy == "classify":
                classified_count += 1
                cls_result = classify_product_safely(
                    row, model, processor, image_path, item_num
                )
                if cls_result["categories"] == "Error":
                    cls_errors += 1
                else:
                    cls_success += 1
                stage = "classified_after_cbd_error"
            else:  # skip
                cls_result = empty_cls_result(
                    category="Error",
                    confidence="low",
                    rationale="CBD filter error; classification skipped.",
                )
                stage = "cbd_error_skipped"

        # ---- Track combination devices + policy overrides ----
        if cls_result.get("combination_device"):
            combination_device_count += 1
        if cls_result.get("policy_override_applied"):
            policy_override_count += 1

        item_time = time.time() - item_start
        item_times.append(item_time)

        # ---- Assemble row (row data + cbd fields + cls fields + routing) ----
        merged = {
            **row.to_dict(),
            **{k: v for k, v in cbd_result.items()
               if k not in ("image_path", "has_image")},
            **cls_result,
            "image_path": cbd_result.get("image_path", ""),
            "has_image": cbd_result.get("has_image", False),
            "pipeline_stage": stage,
            "model_used": args.model_dir.rstrip("/").split("/")[-1],
        }
        results.append(merged)

        # ---- Progress line ----
        if is_cbd is True:
            status = "CBD (filtered)"
        elif is_cbd is False:
            status = f"CLS {cls_result['categories']}"
            if cbd_result.get("cbd_guard_applied"):
                status = "CBD-GUARD -> " + status
        else:
            status = "CBD-ERR " + ("-> CLS " + cls_result["categories"]
                                   if stage.startswith("classified") else "(skipped)")
        if cls_result.get("policy_rule_id"):
            status += (f" [{cls_result['policy_rule_id']}: "
                       f"{cls_result.get('pre_override_category')}]")
        combo_status = " [COMBO]" if cls_result.get("combination_device") else ""
        avg_time = sum(item_times) / len(item_times)
        eta = datetime.now() + timedelta(seconds=avg_time * (len(df) - item_num))
        print(
            f"[{item_num}/{len(df)}] {status}{combo_status} | "
            f"{item_time:.1f}s | "
            f"ETA: {eta.strftime('%H:%M:%S')} | "
            f"{str(row.get('product_name', ''))[:40]}"
        )

        if item_num % args.checkpoint_interval == 0:
            pd.DataFrame(results).to_csv(args.output, index=False)
            langfuse_client.flush()
            print(f"  -> Checkpoint | Elapsed: {format_time(time.time()-start_time)} | "
                  f"CBD+: {cbd_positive} | Classified: {classified_count} | "
                  f"CBD-err: {cbd_errors} | CLS-err: {cls_errors} | "
                  f"Combo: {combination_device_count} | CBD-guard: {cbd_guard_count} | "
                  f"Overrides: {policy_override_count}")

    # -----------------------------------------------------------------------
    # Final save + summary
    # -----------------------------------------------------------------------
    pd.DataFrame(results).to_csv(args.output, index=False)
    langfuse_client.flush()

    total_time = time.time() - start_time
    n = max(len(results), 1)
    print("\n" + "=" * 70)
    print("MERGED PIPELINE SUMMARY (this chunk)")
    print("=" * 70)
    print(f"Total runtime:              {format_time(total_time)}")
    print(f"Model load time:            {format_time(model_load_time)}")
    print(f"Average time per item:      {sum(item_times)/n:.2f}s")
    print(f"Items per minute:           {len(results) / (total_time / 60):.1f}")
    print("-" * 70)
    print(f"Total products:             {len(results)}")
    images_found = sum(1 for r in results if r.get("has_image") is True)
    print(f"Products with image found:  {images_found} of {len(results)}")
    print(f"CBD-positive (filtered):    {cbd_positive} ({cbd_positive/n*100:.1f}%)")
    print(f"Sent to classifier:         {classified_count}")
    print(f"  successful:               {cls_success}")
    print(f"  errors:                   {cls_errors}")
    print(f"Combination devices:        {combination_device_count}")
    print(f"CBD guard -> classified:    {cbd_guard_count}")
    print(f"Policy overrides applied:   {policy_override_count}")
    print(f"CBD filter errors:          {cbd_errors} "
          f"(policy={args.cbd_error_policy})")
    print("=" * 70)
    print(f"\nResults saved to: {args.output}")
    print(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
