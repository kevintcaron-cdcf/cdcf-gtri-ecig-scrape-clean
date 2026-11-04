"""Perfect Vape scraper using the shared BigCommerce implementation."""

from bigcommerce_common import run
from db.db_azure import PERFECT_VAPE


CONFIG = {
    "name": "PERFECT_VAPE",
    "base": "https://perfectvape.com",
    "site": PERFECT_VAPE,
    "links": [
        "/new-hot-items/",
        "/disposables-1/",
        "/0-nicotine-disposable-vapes/",
        "/3-nicotine-disposable-vapes/",
        "/4-nicotine-disposable-vapes/",
        "/5-nicotine-disposable-vapes/",
        "/rechargeable-disposable-vapes/",
        "/smart-disposable-vapes/",
        "/premium-e-liquids/",
        "/salt-nic/",
        "/e-liquid-juices/",
        "/starter-kits/",
        "/pod-systems/",
        "/nicotine-pouches/",
    ],
}


if __name__ == "__main__":
    run(CONFIG)
