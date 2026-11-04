"""Spree Bar Sales WooCommerce Store API scraper.

The public catalog sells Metatine vape pods and starter kits rather than
nicotine pouches. Batteries and display accessories are excluded.
"""

import html
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

import requests

SCRAPING_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = SCRAPING_DIR.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from db.db_azure import (  # noqa: E402
    SPREE_BAR_SALES,
    get_product_id,
    insert_ecig_price,
    insert_product_images,
    map_product_data,
    product_has_images,
    sync_ecig_product_history,
)
from ecig_parsing import (  # noqa: E402
    download_image_batch,
    extract_battery,
    find_features,
    normalize_site_category,
)

BASE = "https://spreebarsales.com"
API = f"{BASE}/wp-json/wc/store/v1/products"
SITE = SPREE_BAR_SALES
PAGE_SIZE = 100
REQUEST_TIMEOUT = 45
REQUEST_DELAY = float(os.getenv("SPREE_BAR_SALES_REQUEST_DELAY", "1.5"))
MAX_PRODUCTS = int(os.getenv("SPREE_BAR_SALES_MAX_PRODUCTS", "0"))
PRODUCT_CATEGORIES = {"starter pack", "starter packs", "flavor pod", "flavor pods"}
EXCLUDED_TITLE_MARKERS = ("battery", "display", "gift card", "shirt")
WRITE_DB = os.getenv("SCRAPE_WRITE_DB", "1").lower() in {"1", "true", "yes"}
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CDCFResearch/1.0)"}


def clean(value):
    text = re.sub(r"<[^>]+>", " ", html.unescape(str(value or "")))
    return re.sub(r"\s+", " ", text).strip()


def price_value(value, minor_unit=2):
    if value in (None, ""):
        return None
    try:
        return f"{int(value) / (10 ** int(minor_unit)):.{int(minor_unit)}f}"
    except (TypeError, ValueError):
        return str(value)


class Fetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.last_request = 0.0

    def get(self, params):
        wait = REQUEST_DELAY - (time.monotonic() - self.last_request)
        if wait > 0:
            time.sleep(wait)
        response = self.session.get(API, params=params, timeout=REQUEST_TIMEOUT)
        self.last_request = time.monotonic()
        response.raise_for_status()
        return response.json()


def categories(product):
    return {str(item.get("name", "")).strip().lower() for item in product.get("categories", [])}


def is_target(product):
    product_categories = categories(product)
    title = str(product.get("name", "")).lower()
    return bool(product_categories & PRODUCT_CATEGORIES) and not any(
        marker in title for marker in EXCLUDED_TITLE_MARKERS
    )


def image_candidates(product):
    return [
        {"url": image.get("src") or image.get("thumbnail"), "alt": image.get("alt") or image.get("name", "")}
        for image in product.get("images", [])
        if image.get("src") or image.get("thumbnail")
    ]


def parse_product(product):
    description = clean(product.get("description"))
    short_description = clean(product.get("short_description"))
    combined = "\n".join(value for value in (description, short_description) if value)
    _, puffs, nicotine, liquid, flavors, devices = find_features(combined)
    prices = product.get("prices") or {}
    minor_unit = prices.get("currency_minor_unit", 2)
    tag = str(product.get("sku") or product.get("slug") or product.get("id"))
    images = download_image_batch(image_candidates(product), tag, f"data_from_sites_v2/{SITE}_images", referer=BASE)
    return {
        "title": clean(product.get("name")),
        "brand": "Spree Bar",
        "link": product.get("permalink") or urljoin(BASE, f"/product/{product.get('slug', '')}/"),
        "site_category": normalize_site_category(next(iter(categories(product)), "")),
        "tag": tag,
        "sku": product.get("sku"),
        "regular_price": price_value(prices.get("regular_price"), minor_unit),
        "sale_price": price_value(prices.get("sale_price"), minor_unit),
        "flavor_text": ", ".join(dict.fromkeys(flavors or [])),
        "description": description,
        "package_contents": "",
        "features": ", ".join(dict.fromkeys(devices or [])),
        "ingredients": "", "warnings": "", "eliquid_contents": liquid,
        "puffs": puffs, "coil": "", "battery": extract_battery(combined),
        "power_level": "", "nicotine_strength": nicotine,
        "stock_status": (product.get("stock_availability") or {}).get("text", ""),
        "reviews": [], "review_attributes": {}, "flavor_list": [],
        "nicotine_strengths": [], "images": images,
        "html": str(product), "plain_text": combined,
    }


def process(product, write_db):
    data = parse_product(product)
    if not write_db:
        print(f"SAMPLE {data['tag']}: {data['title']} [{data['stock_status']}]")
        return
    product_id = get_product_id(SITE, data["tag"])
    if product_id:
        insert_ecig_price(product_id, data["regular_price"], data["sale_price"])
        sync_ecig_product_history(product_id, data)
        if not product_has_images(product_id):
            insert_product_images(product_id, data["images"])
    else:
        map_product_data(SITE, data)


def main(sample=False, write_db=WRITE_DB):
    fetcher = Fetcher()
    products = []
    for page in range(1, 20):
        batch = fetcher.get({"per_page": PAGE_SIZE, "page": page})
        if not batch:
            break
        products.extend(product for product in batch if is_target(product))
        if len(batch) < PAGE_SIZE:
            break
    print(f"{SITE} {BASE}/shop/: {len(products)} target products")
    for index, product in enumerate(products, start=1):
        if MAX_PRODUCTS and index > MAX_PRODUCTS:
            break
        try:
            process(product, False if sample else write_db)
            if sample:
                return
        except Exception as error:
            print(f"SKIP product {product.get('id')}: {error}")


if __name__ == "__main__":
    main(sample=os.getenv("SPREE_BAR_SALES_SAMPLE", "0").lower() in {"1", "true", "yes"})
