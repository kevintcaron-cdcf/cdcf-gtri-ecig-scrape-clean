"""Outlaw Dip Shopify scraper for Reloads and Berserker pouch products."""

import os
import sys
from pathlib import Path

SCRAPING_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = SCRAPING_DIR.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

if __package__:
    from . import alp_pouch as _catalog
else:
    if str(SCRAPING_DIR) not in sys.path:
        sys.path.insert(0, str(SCRAPING_DIR))
    import alp_pouch as _catalog

from db.db_azure import OUTLAW_DIP


BASE = "https://outlawdip.com"
SITE = OUTLAW_DIP
COLLECTION = "/collections/pouches"

_catalog.BASE = BASE
_catalog.SITE = SITE
_catalog.COLLECTION = COLLECTION
_catalog.REQUEST_DELAY = float(os.getenv("OUTLAW_DIP_REQUEST_DELAY", "1.5"))
_catalog.MAX_PRODUCTS = int(os.getenv("OUTLAW_DIP_MAX_PRODUCTS", "0"))
_BASE_LISTING_CARD = _catalog.listing_card


def listing_products(fetcher):
    """Use Shopify's complete public catalog because the collection JSON is empty."""
    payload = fetcher.get(f"{BASE}/products.json?limit=250", json_response=True)
    return payload.get("products", [])


def listing_card(product):
    product_type = (product.get("product_type") or "").strip().lower()
    title = (product.get("title") or "").strip().lower()
    is_berserker = product_type == "caffeine pouches"
    is_reload = "reloads" in title and "pouch" in title
    if not (is_berserker or is_reload):
        return None
    return _BASE_LISTING_CARD({**product, "product_type": "Caffeine Pouches"})


def main(sample=False, write_db=None):
    if write_db is None:
        write_db = os.getenv("SCRAPE_WRITE_DB", "1").lower() in {"1", "true", "yes"}
    original_listing_products = _catalog.listing_products
    original_listing_card = _catalog.listing_card
    _catalog.listing_products = listing_products
    _catalog.listing_card = listing_card
    try:
        _catalog.main(sample=sample, write_db=write_db)
    finally:
        _catalog.listing_products = original_listing_products
        _catalog.listing_card = original_listing_card


if __name__ == "__main__":
    main(sample=os.getenv("OUTLAW_DIP_SAMPLE", "0").lower() in {"1", "true", "yes"})
