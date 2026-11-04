"""Nic Pouches USA Shopify scraper for nicotine pouch products."""

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

from db.db_azure import NIC_POUCHES_US


BASE = "https://nicpouches.us"
SITE = NIC_POUCHES_US
COLLECTION = "/collections/all"
EXCLUDED_TITLE_MARKERS = ("sampler", "bundle", "sticker", "t-shirt", "shirt")

_catalog.BASE = BASE
_catalog.SITE = SITE
_catalog.COLLECTION = COLLECTION
_catalog.REQUEST_DELAY = float(os.getenv("NIC_POUCHES_US_REQUEST_DELAY", "1.5"))
_catalog.MAX_PRODUCTS = int(os.getenv("NIC_POUCHES_US_MAX_PRODUCTS", "0"))
_BASE_LISTING_CARD = _catalog.listing_card


def listing_card(product):
    product_type = (product.get("product_type") or "").strip().lower()
    title = (product.get("title") or "").strip().lower()
    if product_type != "nic pouches" or any(marker in title for marker in EXCLUDED_TITLE_MARKERS):
        return None
    return _BASE_LISTING_CARD({**product, "product_type": "Nicotine Pouches"})


def main(sample=False, write_db=None):
    if write_db is None:
        write_db = os.getenv("SCRAPE_WRITE_DB", "1").lower() in {"1", "true", "yes"}
    original = _catalog.listing_card
    _catalog.listing_card = listing_card
    try:
        _catalog.main(sample=sample, write_db=write_db)
    finally:
        _catalog.listing_card = original


if __name__ == "__main__":
    main(sample=os.getenv("NIC_POUCHES_US_SAMPLE", "0").lower() in {"1", "true", "yes"})
