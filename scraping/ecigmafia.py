"""ECigMafia scraper."""

from bigcommerce_common import run
from db.db_azure import ECIGMAFIA

CONFIG = {
    "name": "ECIGMAFIA",
    "base": "https://www.ecigmafia.com",
    "site": ECIGMAFIA,
    "links": ["/disposables-vape/", "/e-liquids/", "/pod-systems/"],
}

if __name__ == "__main__":
    run(CONFIG)
