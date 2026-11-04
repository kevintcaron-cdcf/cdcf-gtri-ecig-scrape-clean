"""Sesh Products Shopify scraper for the official Sesh+ pouch catalog.

The collection also contains cans, apparel, bundles, and equipment.  Only
individual products whose Shopify type is ``Pouches`` are synchronized.
"""

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

from db.db_azure import SESH_PRODUCTS


BASE = "https://seshproducts.com"
SITE = SESH_PRODUCTS
COLLECTION = "/collections/nicotine-pouches"
EXCLUDED_TITLE_MARKERS = ("bundle", "variety pack")

# Reuse the tested Shopify fetching, parsing, image, review, and Azure flow.
_catalog.BASE = BASE
_catalog.SITE = SITE
_catalog.COLLECTION = COLLECTION
_catalog.REQUEST_DELAY = float(os.getenv("SESH_PRODUCTS_REQUEST_DELAY", "1.5"))
_catalog.MAX_PRODUCTS = int(os.getenv("SESH_PRODUCTS_MAX_PRODUCTS", "0"))
_BASE_LISTING_CARD = _catalog.listing_card


def listing_card(product):
    """Keep pouch units and refill bags; exclude collection accessories/bundles."""
    product_type = (product.get("product_type") or "").strip().lower()
    title = (product.get("title") or "").strip().lower()
    if product_type != "pouches" or any(marker in title for marker in EXCLUDED_TITLE_MARKERS):
        return None
    return _BASE_LISTING_CARD({**product, "product_type": "Nicotine Pouches"})


def main(sample=False, write_db=None):
    if write_db is None:
        write_db = os.getenv("SCRAPE_WRITE_DB", "1").lower() in {"1", "true", "yes"}
    # The shared implementation calls this module's globals, so replace only
    # its collection filter while retaining the conservative request flow.
    original = _catalog.listing_card
    _catalog.listing_card = listing_card
    try:
        _catalog.main(sample=sample, write_db=write_db)
    finally:
        _catalog.listing_card = original


if __name__ == "__main__":
    main(sample=os.getenv("SESH_PRODUCTS_SAMPLE", "0").lower() in {"1", "true", "yes"})
