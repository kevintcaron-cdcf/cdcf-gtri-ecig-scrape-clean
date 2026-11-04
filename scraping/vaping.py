"""Vaping.com scraper."""

from bigcommerce_common import run
from db.db_azure import VAPING_DOT_COM

CONFIG = {
    "name": "VAPING.COM",
    "base": "https://vaping.com",
    "site": VAPING_DOT_COM,
    "links": ["/collections/disposable-vapes/", "/collections/pod-systems/", "/collections/e-liquids/"],
}

if __name__ == "__main__":
    run(CONFIG)
