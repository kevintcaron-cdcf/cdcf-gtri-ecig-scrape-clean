"""ALP Pouch Shopify scraper for nicotine and caffeine pouch products."""

import json
import os
import re
import sys
import time
from html import unescape
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from db.db_azure import (  # noqa: E402
    ALP_POUCH,
    get_product_id,
    insert_ecig_price,
    insert_product_images,
    insert_reviews,
    map_product_data,
    product_has_images,
    sync_ecig_product_history,
)
from ecig_parsing import (  # noqa: E402
    download_image_batch,
    extract_battery,
    extract_reviews,
    find_features,
    normalize_site_category,
)

BASE = "https://alppouch.com"
SITE = ALP_POUCH
COLLECTION = "/collections/all-products"
PER_PAGE = 250
REQUEST_TIMEOUT = 45
REQUEST_DELAY = float(os.getenv("ALP_POUCH_REQUEST_DELAY", "1.5"))
MAX_PRODUCTS = int(os.getenv("ALP_POUCH_MAX_PRODUCTS", "0"))
WRITE_DB = os.getenv("SCRAPE_WRITE_DB", "1").lower() in {"1", "true", "yes"}
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CDCFResearch/1.0)"}
PRODUCT_TYPES = {"nicotine pouches", "caffeine pouches"}
BLOCK_MARKERS = ("access denied", "verify you are human", "captcha")


def canonical_url(value):
    parts = urlsplit(urljoin(BASE, value or ""))
    return urlunsplit(("https", parts.netloc or "alppouch.com", parts.path.rstrip("/") or "/", "", ""))


def clean(value):
    return re.sub(r"\s+", " ", BeautifulSoup(str(value or ""), "lxml").get_text(" ", strip=True)).strip()


def money(value):
    match = re.search(r"\d+(?:,\d{3})*(?:\.\d{1,2})?", str(value or ""))
    return match.group(0).replace(",", "") if match else None


class Fetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.cache = {}
        self.last_request = 0.0

    def get(self, url, json_response=False):
        url = url if url.endswith(".json") or "products.json" in url else canonical_url(url)
        if url in self.cache:
            return self.cache[url]
        wait = REQUEST_DELAY - (time.monotonic() - self.last_request)
        if wait > 0:
            time.sleep(wait)
        response = self.session.get(url, timeout=REQUEST_TIMEOUT)
        self.last_request = time.monotonic()
        body = response.text[:100000].lower()
        if response.status_code in {403, 429, 503} or (
            any(marker in body for marker in BLOCK_MARKERS)
            and len(response.text) < 100000
        ):
            raise RuntimeError(f"ALP access/rate-limit response {response.status_code}: {url}")
        response.raise_for_status()
        payload = response.json() if json_response else response.text
        self.cache[url] = payload
        return payload


def listing_products(fetcher):
    payload = fetcher.get(f"{BASE}{COLLECTION}/products.json?limit={PER_PAGE}", json_response=True)
    return payload.get("products", [])


def listing_card(product):
    if product.get("product_type", "").strip().lower() not in PRODUCT_TYPES:
        return None
    handle = product.get("handle")
    variants = product.get("variants") or []
    if not handle or not variants:
        return None
    first = variants[0]
    current = money(first.get("price"))
    compare = money(first.get("compare_at_price"))
    return {
        "url": canonical_url(f"/products/{handle}"), "tag": handle,
        "title": clean(product.get("title")), "brand": clean(product.get("vendor")) or "ALP",
        "regular_price": compare or current, "sale_price": current if compare else None,
        "stock_status": "In Stock" if any(v.get("available") for v in variants) else "Out of Stock",
        "product": product, "site_category": normalize_site_category(COLLECTION),
    }


def parse_product(card, html):
    product = card["product"]
    soup = BeautifulSoup(html, "lxml")
    description = clean(product.get("body_html") or soup.select_one(".product__description, .product-description"))
    combined = "\n".join((description, soup.get_text(" ", strip=True)))
    _, puffs, nicotine, liquid, flavors, devices = find_features(combined)
    variants = product.get("variants") or []
    nicotine_levels = []
    for variant in variants:
        option = " ".join(str(variant.get(key) or "") for key in ("title", "option1", "option2", "option3"))
        match = re.search(r"(\d+(?:\.\d+)?)\s*(mg(?:/pouch|/ml)?|%)", option, re.I)
        if match:
            nicotine_levels.append({"value": float(match.group(1)), "unit": match.group(2), "level": None})
    images, seen = [], set()
    for image in product.get("images") or []:
        source = image.get("src") if isinstance(image, dict) else image
        source = urljoin(BASE, source or "")
        if source and source not in seen:
            seen.add(source)
            images.append({"url": source, "alt": card["title"]})
    return {
        "title": card["title"], "brand": card["brand"], "link": card["url"],
        "site_category": card["site_category"], "tag": card["tag"],
        "sku": variants[0].get("sku"), "regular_price": card["regular_price"],
        "sale_price": card["sale_price"], "flavor_text": ", ".join(dict.fromkeys(flavors or [])),
        "description": description, "package_contents": "", "features": ", ".join(dict.fromkeys(devices or [])),
        "ingredients": "", "warnings": "", "eliquid_contents": liquid, "puffs": puffs, "coil": "",
        "battery": extract_battery(combined), "power_level": "", "nicotine_strength": nicotine,
        "stock_status": card["stock_status"], "reviews": extract_reviews(soup), "review_attributes": {},
        "flavor_list": [], "nicotine_strengths": nicotine_levels, "image_urls": images,
        "html": html, "plain_text": soup.get_text(" ", strip=True),
    }


def main(sample=False, write_db=WRITE_DB):
    fetcher = Fetcher()
    cards = [listing_card(product) for product in listing_products(fetcher)]
    cards = [card for card in cards if card]
    print(f"{SITE} {BASE}{COLLECTION}: {len(cards)} pouch products")
    for processed, card in enumerate(cards, start=1):
        if MAX_PRODUCTS and processed > MAX_PRODUCTS:
            break
        try:
            data = parse_product(card, fetcher.get(card["url"]))
            if sample or not write_db:
                print(f"SAMPLE {data['tag']}: {data['title']} [{data['stock_status']}]")
                if sample:
                    return
                continue
            product_id = get_product_id(SITE, data["tag"])
            if product_id:
                sync_ecig_product_history(product_id, data)
                insert_ecig_price(product_id, data["regular_price"], data["sale_price"])
                if data["reviews"]:
                    insert_reviews(data["reviews"], product_id)
                if not product_has_images(product_id):
                    images = download_image_batch(data.pop("image_urls"), data["tag"], f"data_from_sites_v2/{SITE}_images", referer=data["link"])
                    insert_product_images(product_id, images)
            else:
                data["images"] = download_image_batch(data.pop("image_urls"), data["tag"], f"data_from_sites_v2/{SITE}_images", referer=data["link"])
                map_product_data(SITE, data)
        except Exception as error:
            print(f"SKIP product {card['url']}: {error}")


if __name__ == "__main__":
    main(sample=os.getenv("ALP_POUCH_SAMPLE", "0").lower() in {"1", "true", "yes"})
