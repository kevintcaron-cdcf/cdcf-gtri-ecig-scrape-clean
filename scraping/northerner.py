"""Northerner USA Magento/Hyva catalog scraper.

Northerner and Nicokick currently expose the same server-rendered Hyva
catalog shape.  The implementation is kept as a small site-specific wrapper
around the tested Nicokick parser while using a distinct database site key.
"""

import os
import sys
from pathlib import Path

SCRAPING_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = SCRAPING_DIR.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

if __package__:
    from . import nicokick as _catalog
else:  # Running as ``python scraping/northerner.py`` from any directory.
    if str(SCRAPING_DIR) not in sys.path:
        sys.path.insert(0, str(SCRAPING_DIR))
    import nicokick as _catalog
from db.db_azure import NORTHERNER


BASE = "https://www.northerner.com"
SITE = NORTHERNER
FALLBACK_CATEGORIES = [
    "/us/nicotine-pouches",
    "/us/nicotine-pouches/zyn",
    "/us/nicotine-pouches/velo",
    "/us/nicotine-pouches/on",
    "/us/nicotine-pouches/rogue",
    "/us/nicotine-pouches/strong-nicotine-strength",
    "/us/nicotine-pouches/extra-nicotine-strength",
    "/us/other-products",
]

# Reuse the conservative parser and database synchronization flow, but point
# all module-level URL/site references at Northerner.
_catalog.BASE = BASE
_catalog.SITEMAP_URL = BASE + "/media/sitemap.xml"
_catalog.SITE = SITE
_catalog.FALLBACK_CATEGORIES = FALLBACK_CATEGORIES


def main(sample=False, write_db=None):
    """Run the Northerner scraper using Northerner-specific env controls."""
    if write_db is None:
        write_db = os.getenv("SCRAPE_WRITE_DB", "1").lower() in {"1", "true", "yes"}
    _catalog.REQUEST_DELAY = float(os.getenv("NORTHERNER_REQUEST_DELAY", "1.5"))
    _catalog.MAX_PAGES = int(os.getenv("NORTHERNER_MAX_PAGES", "100"))
    _catalog.MAX_PRODUCTS = int(os.getenv("NORTHERNER_MAX_PRODUCTS", "0"))
    _catalog.main(sample=sample, write_db=write_db)


if __name__ == "__main__":
    main(sample=os.getenv("NORTHERNER_SAMPLE", "0").lower() in {"1", "true", "yes"})
