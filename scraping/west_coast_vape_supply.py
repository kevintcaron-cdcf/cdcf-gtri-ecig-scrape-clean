"""West Coast Vape Supply BigCommerce storefront scraper."""

import os
import sys
import requests
from bs4 import BeautifulSoup
from pathlib import Path

SCRAPING_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = SCRAPING_DIR.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

if __package__:
    from . import bigcommerce_common as _catalog
else:
    if str(SCRAPING_DIR) not in sys.path:
        sys.path.insert(0, str(SCRAPING_DIR))
    import bigcommerce_common as _catalog

from db.db_azure import WEST_COAST_VAPE_SUPPLY


BASE = "https://westcoastvapesupply.com"
SITE = WEST_COAST_VAPE_SUPPLY
LINKS = ["/shop-all/"]

_catalog.DELAY = float(os.getenv("WEST_COAST_VAPE_SUPPLY_REQUEST_DELAY", "10"))
_catalog.MAX_PAGES = int(os.getenv("WEST_COAST_VAPE_SUPPLY_MAX_PAGES", "200"))


def main(sample=False, write_db=None):
    if write_db is None:
        write_db = os.getenv("SCRAPE_WRITE_DB", "1").lower() in {"1", "true", "yes"}
    if sample:
        response = requests.get(f"{BASE}/shop-all/", headers={"User-Agent": "Mozilla/5.0"}, timeout=45)
        response.raise_for_status()
        card_node = _catalog.cards(BeautifulSoup(response.text, "lxml"))[0]
        card = _catalog.parse_card(card_node, BASE)
        detail = requests.get(card["url"], headers={"User-Agent": "Mozilla/5.0"}, timeout=45)
        detail.raise_for_status()
        parsed = _catalog.parse_product(card, detail.text, "/shop-all/", BASE, SITE)
        print(f"{SITE} {BASE}/shop-all/: sample product {parsed['tag']}: {parsed['title']} [{parsed['regular_price']}]")
        return
    config = {
        "name": SITE,
        "base": BASE,
        "site": SITE,
        "links": LINKS,
    }
    _catalog.run(config)


if __name__ == "__main__":
    main(sample=os.getenv("WEST_COAST_VAPE_SUPPLY_SAMPLE", "0").lower() in {"1", "true", "yes"})
