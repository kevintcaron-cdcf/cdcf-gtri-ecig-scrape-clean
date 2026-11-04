"""Conservative Huff and Puffers WooCommerce scraper.

The retailer exposes a public WooCommerce Store API. This scraper uses that
catalog endpoint instead of browser automation, keeps a local successful-page
cache, and stops on block-like responses. Database writes are enabled by
default; set SCRAPE_WRITE_DB=0 for a dry run.
"""

import hashlib
import argparse
import json
import os
import re
import sys
import time
from html import unescape
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit

import requests

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from db.db_azure import (  # noqa: E402
    get_product_id,
    insert_ecig_price,
    insert_product_images,
    insert_reviews,
    map_product_data,
    product_has_images,
    sync_ecig_product_history,
    HUFF_AND_PUFFERS,
)
try:
    from ecig_parsing import (  # noqa: E402
        download_image_batch,
        extract_battery,
        find_features,
        normalize_site_category,
        prioritize_links,
    )
except ModuleNotFoundError:  # Support importing as scraping.huffandpuffers.
    from scraping.ecig_parsing import (  # noqa: E402
        download_image_batch,
        extract_battery,
        find_features,
        normalize_site_category,
        prioritize_links,
    )


BASE = "https://www.huffandpuffers.com"
API = f"{BASE}/wp-json/wc/store/v1/products"
SITE = HUFF_AND_PUFFERS
PAGE_SIZE = 50
MAX_PAGES = int(os.getenv("HUFF_AND_PUFFERS_MAX_PAGES", "200"))
REQUEST_TIMEOUT = 45
REQUEST_DELAY = float(os.getenv("HUFF_AND_PUFFERS_REQUEST_DELAY", "2"))
WRITE_DB = os.getenv("SCRAPE_WRITE_DB", "1").lower() in {"1", "true", "yes"}
CACHE_DIR = Path(__file__).with_name("cache") / "huffandpuffers"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0 Safari/537.36"
)
BLOCK_MARKERS = (
    "access denied",
    "captcha",
    "cloudflare",
    "just a moment",
    "verify you are human",
)


def request_url(url, params=None):
    parts = urlsplit(urljoin(BASE, url))
    query = urlencode(params or {})
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), query, ""))


def cache_path(url):
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{key}.json"


def cache_load(url):
    path = cache_path(url)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def cache_save(url, payload):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path(url).write_text(json.dumps(payload), encoding="utf-8")


def block_reason(response):
    content = (response.text or "")[:100000].lower()
    if response.status_code in {403, 429}:
        return f"HTTP {response.status_code}"
    return next((marker for marker in BLOCK_MARKERS if marker in content), None)


class Fetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/plain;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.8",
        })
        self.last_request = 0.0

    def get_json(self, url, params=None):
        full_url = request_url(url, params)
        cached = cache_load(full_url)
        if cached is not None:
            print(f"CACHE {full_url}")
            return cached
        elapsed = time.monotonic() - self.last_request
        if elapsed < REQUEST_DELAY:
            time.sleep(REQUEST_DELAY - elapsed)
        response = self.session.get(full_url, timeout=REQUEST_TIMEOUT)
        self.last_request = time.monotonic()
        reason = block_reason(response)
        if reason:
            raise RuntimeError(f"Huff and Puffers blocked {full_url}: {reason}")
        response.raise_for_status()
        payload = response.json()
        cache_save(full_url, payload)
        return payload


def html_text(value):
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", unescape(value)).strip()


def price(product):
    prices = product.get("prices") or {}
    minor_unit = int(prices.get("currency_minor_unit", 2) or 2)
    divisor = 10 ** minor_unit

    def convert(value):
        if value in (None, ""):
            return None
        try:
            return f"{int(value) / divisor:.{minor_unit}f}"
        except (TypeError, ValueError):
            return str(value)

    return convert(prices.get("regular_price")), convert(prices.get("sale_price"))


def category_name(product):
    categories = product.get("categories") or []
    return normalize_site_category(categories[0].get("name", "")) if categories else ""


def product_tag(product):
    return str(product.get("sku") or product.get("slug") or product.get("id"))


def parse_images(product):
    candidates = []
    for image in product.get("images") or []:
        src = image.get("src") or image.get("thumbnail")
        if src:
            candidates.append({"url": src, "alt": image.get("alt") or image.get("name", "")})
    return candidates


def build_image_candidates(product):
    """Prefer a format Pillow can read when the API only supplies AVIF."""
    candidates = []
    for image in product.get("images") or []:
        source = image.get("src") or image.get("thumbnail")
        if not source:
            continue
        values = [image.get("src"), image.get("thumbnail")]
        values.extend(
            part.strip().split(" ")[0]
            for part in (image.get("srcset") or "").split(",")
            if part.strip()
        )
        fallback = next((value for value in values if value and ".avif" not in value.lower()), source)
        candidates.append({"url": fallback, "alt": image.get("alt") or image.get("name", "")})
    return candidates


def parse_product(product):
    description = html_text(product.get("description"))
    short_description = html_text(product.get("short_description"))
    combined = "\n".join(value for value in (description, short_description) if value)
    _, puffs, nicotine, liquid, flavor_text, device_features = find_features(combined)
    flavor_text = ", ".join(dict.fromkeys(flavor_text or []))
    device_features = ", ".join(dict.fromkeys(device_features or []))
    regular_price, sale_price = price(product)
    tag = product_tag(product)
    brand = next((item.get("name") for item in product.get("brands") or []), "")
    image_candidates = build_image_candidates(product)
    images = download_image_batch(
        image_candidates, tag, f"data_from_sites_v2/{SITE}_images", referer=BASE
    )
    return {
        "title": html_text(product.get("name")),
        "link": product.get("permalink") or urljoin(BASE, f"/products/{product.get('slug', '')}"),
        "site_category": category_name(product),
        "tag": tag,
        "brand": brand,
        "html": json.dumps(product, ensure_ascii=False),
        "plain_text": combined,
        "regular_price": regular_price,
        "sale_price": sale_price,
        "flavor_text": flavor_text,
        "description": description,
        "package_contents": "",
        "features": device_features,
        "ingredients": "",
        "warnings": "",
        "eliquid_contents": liquid,
        "puffs": puffs,
        "coil": "",
        "battery": extract_battery(combined),
        "power_level": "",
        "nicotine_strength": nicotine,
        "stock_status": (product.get("stock_availability") or {}).get("text", ""),
        "reviews": [],
        "review_attributes": {},
        "flavor_list": [],
        "nicotine_strengths": [],
        "images": images,
    }


def process_product(product):
    data = parse_product(product)
    product_id = get_product_id(SITE, data["tag"]) if WRITE_DB else None
    if not WRITE_DB:
        return data
    if product_id:
        insert_ecig_price(product_id, data["regular_price"], data["sale_price"])
        sync_ecig_product_history(product_id, data)
        if not product_has_images(product_id):
            insert_product_images(product_id, data["images"])
        if data["reviews"]:
            insert_reviews(data["reviews"], product_id)
    else:
        map_product_data(SITE, data)
    return data


def discover_categories(fetcher):
    categories = fetcher.get_json(f"{BASE}/wp-json/wc/store/v1/products/categories", {"per_page": 100})
    paths = [item.get("permalink") for item in categories if item.get("permalink")]
    return prioritize_links(paths)


def main(write_db=WRITE_DB):
    global WRITE_DB
    WRITE_DB = write_db
    fetcher = Fetcher()
    seen = set()
    stats = {"pages": 0, "products": 0, "new_or_parsed": 0, "errors": 0}
    try:
        categories = discover_categories(fetcher)
        print(f"Discovered {len(categories)} Huff and Puffers categories")
        params = {"per_page": PAGE_SIZE, "page": 1}
        for page in range(1, MAX_PAGES + 1):
            params["page"] = page
            products = fetcher.get_json(API, params)
            stats["pages"] += 1
            if not products:
                break
            for product in products:
                product_id = product.get("id")
                if not product_id or product_id in seen:
                    continue
                seen.add(product_id)
                stats["products"] += 1
                process_product(product)
                stats["new_or_parsed"] += 1
            print(f"PAGE {page}: {len(products)} products")
            if len(products) < PAGE_SIZE:
                break
        print(f"Huff and Puffers summary: {stats}; DB writes={'enabled' if WRITE_DB else 'disabled'}")
    except Exception as error:
        stats["errors"] += 1
        print(f"Stopping Huff and Puffers scraper: {error}")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape Huff and Puffers products")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="parse products without writing to Azure SQL",
    )
    args = parser.parse_args()
    main(write_db=WRITE_DB and not args.dry_run)
