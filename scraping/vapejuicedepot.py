"""Vape Juice Depot Shopify scraper."""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from db.db_azure import (  # noqa: E402
    VAPE_JUICE_DEPOT,
    get_product_id,
    insert_ecig_price,
    insert_product_images,
    insert_reviews,
    map_product_data,
    product_has_images,
    sync_ecig_product_history,
)
try:
    from ecig_parsing import (  # noqa: E402
        download_image_batch,
        extract_battery,
        find_features,
        normalize_site_category,
        prioritize_links,
    )
except ModuleNotFoundError:  # Support importing as scraping.vapejuicedepot.
    from scraping.ecig_parsing import (  # noqa: E402
        download_image_batch,
        extract_battery,
        find_features,
        normalize_site_category,
        prioritize_links,
    )


BASE = "https://vapejuicedepot.com"
TEXT_PROXY = "https://r.jina.ai/http://vapejuicedepot.com"
SITE = VAPE_JUICE_DEPOT
PER_PAGE = 250
MAX_PAGES = int(os.getenv("VAPE_JUICE_DEPOT_MAX_PAGES", "20"))
REQUEST_TIMEOUT = 45
REQUEST_DELAY = float(os.getenv("VAPE_JUICE_DEPOT_REQUEST_DELAY", "2"))
WRITE_DB = os.getenv("SCRAPE_WRITE_DB", "1").lower() in {"1", "true", "yes"}
CACHE_DIR = Path(__file__).with_name("cache") / "vapejuicedepot"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CDCFResearch/1.0)"}
FALLBACK_COLLECTIONS = [
    "/collections/new-arrivals",
    "/collections/disposable-vape",
    "/collections/vape-juice",
    "/collections/nicotine-salts",
    "/collections/freebase-e-liquids",
    "/collections/vape-devices",
    "/collections/nicotine-pouches",
    "/collections/final-sale",
]
BLOCK_MARKERS = (
    "web page blocked",
    "access denied",
    "captcha",
    "cloudflare",
    "just a moment",
    "verify you are human",
)


def canonical_url(value):
    parts = urlsplit(urljoin(BASE, value or ""))
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def product_tag(url):
    return urlsplit(canonical_url(url)).path.rstrip("/").split("/")[-1]


def cache_path(url):
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{key}.json"


def cached(url):
    path = cache_path(url)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_cache(url, payload):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path(url).write_text(json.dumps(payload), encoding="utf-8")


def block_reason(response):
    body = (response.text or "")[:100000].lower()
    if response.status_code in {403, 429, 503}:
        return f"HTTP {response.status_code}"
    return next((marker for marker in BLOCK_MARKERS if marker in body), None)


class Fetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.last_request = 0.0

    def get(self, url, as_json=False):
        url = url if "products.json" in url else canonical_url(url)
        saved = cached(url)
        if saved is not None:
            print(f"CACHE {url}")
            return saved
        elapsed = time.monotonic() - self.last_request
        if elapsed < REQUEST_DELAY:
            time.sleep(REQUEST_DELAY - elapsed)
        response = self.session.get(url, timeout=REQUEST_TIMEOUT)
        self.last_request = time.monotonic()
        reason = block_reason(response)
        if reason:
            raise RuntimeError(f"Vape Juice Depot blocked {url}: {reason}")
        response.raise_for_status()
        payload = response.json() if as_json else response.text
        save_cache(url, payload)
        return payload

    def get_proxy_text(self, path):
        """Fetch readable HTML through the text proxy when direct access fails."""
        proxy_url = f"{TEXT_PROXY}{path}"
        saved = cached(proxy_url)
        if saved is not None:
            print(f"CACHE {proxy_url}")
            return saved
        response = requests.get(proxy_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        save_cache(proxy_url, response.text)
        return response.text


def text(value):
    value = BeautifulSoup(value or "", "lxml").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", unescape(value)).strip()


def money(value):
    match = re.search(r"\d+(?:,\d{3})*(?:\.\d{1,2})?", str(value or ""))
    return match.group(0).replace(",", "") if match else None


def discover_collections(fetcher):
    links = list(FALLBACK_COLLECTIONS)
    try:
        html = fetcher.get(BASE)
        soup = BeautifulSoup(html, "lxml")
        hrefs = [anchor.get("href") for anchor in soup.select('a[href*="/collections/"]')]
    except (requests.RequestException, RuntimeError) as error:
        print(f"Direct category discovery unavailable; using collection sitemap proxy: {error}")
        sitemap = fetcher.get_proxy_text("/sitemap_collections_1.xml")
        hrefs = re.findall(r"https?://[^)\s\]]+/collections/[^)\s\]]+", sitemap)
    for href in hrefs:
        path = urlsplit(canonical_url(href)).path
        if path.startswith("/collections/") and path not in links:
            links.append(path)
    return prioritize_links(links)


def listing_products(fetcher, collection, page):
    url = f"{BASE}{collection}/products.json?limit={PER_PAGE}&page={page}"
    payload = fetcher.get(url, as_json=True)
    return payload.get("products", [])


def listing_card(product, collection):
    handle = product.get("handle")
    if not handle:
        return None
    url = canonical_url(f"/products/{handle}")
    variants = product.get("variants") or []
    first = variants[0] if variants else {}
    compare = money(first.get("compare_at_price"))
    current = money(first.get("price"))
    return {
        "url": url,
        "tag": product_tag(url),
        "title": product.get("title", "").strip(),
        "brand": product.get("vendor", "").strip(),
        "regular_price": compare or current,
        "sale_price": current if compare else None,
        "site_category": normalize_site_category(collection),
        "listing": product,
    }


def structured_product(soup):
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(node.string or node.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        values = value if isinstance(value, list) else [value]
        for item in values:
            if isinstance(item, dict) and item.get("@type") == "Product":
                return item
    return {}


def parse_product(card, html):
    soup = BeautifulSoup(html, "lxml")
    listing = card["listing"]
    structured = structured_product(soup)
    title = structured.get("name") or card["title"]
    description_html = listing.get("body_html") or structured.get("description") or ""
    description = text(description_html)
    combined = "\n".join((description, soup.get_text(" ", strip=True)))
    _, puffs, nicotine, liquid, flavors, devices = find_features(combined)
    flavors = ", ".join(dict.fromkeys(flavors or []))
    devices = ", ".join(dict.fromkeys(devices or []))
    nicotine_levels = []
    for variant in listing.get("variants") or []:
        value = variant.get("title") or variant.get("option1") or ""
        match = re.search(r"(\d+(?:\.\d+)?)\s*(mg(?:/ml)?|%)", value, re.I)
        if match:
            nicotine_levels.append({"value": float(match.group(1)), "unit": match.group(2), "level": None})
    images = []
    seen = set()
    for image in listing.get("images") or []:
        source = image.get("src") if isinstance(image, dict) else image
        source = urljoin(BASE, source or "").replace("http://", "https://", 1)
        lower_source = source.lower()
        if (
            source
            and source not in seen
            and not any(marker in lower_source for marker in ("logo", "favicon", "icon-"))
        ):
            seen.add(source)
            images.append({"url": source, "alt": title})
    saved_images = download_image_batch(images, card["tag"], f"data_from_sites_v2/{SITE}_images", referer=card["url"])
    brand = structured.get("brand", {})
    brand = brand.get("name") if isinstance(brand, dict) else brand
    return {
        "title": title,
        "brand": brand or card["brand"],
        "link": card["url"],
        "site_category": card["site_category"],
        "tag": card["tag"],
        "html": html,
        "plain_text": combined,
        "regular_price": card["regular_price"],
        "sale_price": card["sale_price"],
        "flavor_text": flavors,
        "description": description,
        "package_contents": "",
        "features": devices,
        "ingredients": "",
        "warnings": "",
        "eliquid_contents": liquid,
        "puffs": puffs,
        "coil": "",
        "battery": extract_battery(combined),
        "power_level": "",
        "nicotine_strength": nicotine,
        "stock_status": "In Stock" if any(v.get("available") for v in listing.get("variants") or []) else "Out of Stock",
        "reviews": [],
        "review_attributes": {},
        "flavor_list": [],
        "nicotine_strengths": nicotine_levels,
        "images": saved_images,
    }


def main(sample=False, write_db=WRITE_DB):
    fetcher = Fetcher()
    seen = set()
    collections = ["/collections/new-arrivals"] if sample else discover_collections(fetcher)
    for collection in collections:
        for page in range(1, MAX_PAGES + 1):
            products = listing_products(fetcher, collection, page)
            print(f"Vape Juice Depot {collection} page {page}: {len(products)} products")
            if not products:
                break
            for raw_product in products:
                card = listing_card(raw_product, collection)
                if not card or card["tag"] in seen:
                    continue
                seen.add(card["tag"])
                html = fetcher.get(card["url"])
                data = parse_product(card, html)
                if sample:
                    print(f"SAMPLE {data['tag']}: {data['title']}")
                    return
                product_id = get_product_id(SITE, card["tag"]) if write_db else None
                if product_id:
                    insert_ecig_price(product_id, data["regular_price"], data["sale_price"])
                    sync_ecig_product_history(product_id, data)
                    if not product_has_images(product_id):
                        insert_product_images(product_id, data["images"])
                    if data["reviews"]:
                        insert_reviews(data["reviews"], product_id)
                elif write_db:
                    map_product_data(SITE, data)
            if len(products) < PER_PAGE:
                break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape Vape Juice Depot Shopify products")
    parser.add_argument("--sample", action="store_true", help="parse one product without database writes")
    parser.add_argument("--dry-run", action="store_true", help="disable database writes")
    args = parser.parse_args()
    main(sample=args.sample, write_db=WRITE_DB and not args.dry_run)
