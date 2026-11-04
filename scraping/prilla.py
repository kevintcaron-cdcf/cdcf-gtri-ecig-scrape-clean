"""Prilla USA Magento scraper.

Prilla serves its USA catalog as server-rendered Magento HTML.  This scraper
uses the public category pages and sitemap rather than Magento's private
endpoints, and deliberately keeps requests sequential and rate limited.
"""

import json
import os
import random
import re
import sys
import time
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from db.db_azure import (  # noqa: E402
    PRILLA,
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
    prioritize_links,
)

BASE = "https://prilla.com"
US_ROOT = "/us"
SITE = PRILLA
REQUEST_TIMEOUT = 45
REQUEST_DELAY = float(os.getenv("PRILLA_REQUEST_DELAY", "1.5"))
MAX_PAGES = int(os.getenv("PRILLA_MAX_PAGES", "100"))
MAX_PRODUCTS = int(os.getenv("PRILLA_MAX_PRODUCTS", "0"))
WRITE_DB = os.getenv("SCRAPE_WRITE_DB", "1").lower() in {"1", "true", "yes"}
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CDCFResearch/1.0)"}
FALLBACK_CATEGORIES = [
    "/us/new-arrivals",
    "/us/nicotine-pouches",
    "/us/strong-nicotine-pouches",
    "/us/zyn-nicotine-pouches",
    "/us/velo-nicotine-pouches",
    "/us/on-nicotine-pouches",
    "/us/other-nicotine-products",
    "/us/special-offers",
    "/us/bestsellers",
]
BLOCK_MARKERS = ("access denied", "verify you are human", "captcha", "challenge")


def canonical_url(value):
    parts = urlsplit(urljoin(BASE, value or ""))
    query = [(key, value) for key, value in parse_qsl(parts.query) if key == "page"]
    return urlunsplit(("https", parts.netloc or "prilla.com", parts.path.rstrip("/") or "/",
                       urlencode(query), ""))


def product_tag(url):
    return urlsplit(canonical_url(url)).path.rstrip("/").split("/")[-1]


def clean(value):
    return re.sub(r"\s+", " ", BeautifulSoup(value or "", "lxml").get_text(" ", strip=True)).strip()


def money(value):
    match = re.search(r"\$?\s*(\d+(?:,\d{3})*(?:\.\d{1,2})?)", str(value or ""))
    return match.group(1).replace(",", "") if match else None


class Fetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.cache = {}
        self.last_request = 0.0

    def get(self, url):
        url = canonical_url(url)
        if url in self.cache:
            return self.cache[url]
        wait = REQUEST_DELAY - (time.monotonic() - self.last_request)
        if wait > 0:
            time.sleep(wait + random.uniform(0, min(.5, wait * .2)))
        response = self.session.get(url, timeout=REQUEST_TIMEOUT)
        self.last_request = time.monotonic()
        body = response.text[:100000].lower()
        if response.status_code in {403, 429, 503} or any(marker in body for marker in BLOCK_MARKERS):
            raise RuntimeError(f"Prilla access/rate-limit response {response.status_code}: {url}")
        response.raise_for_status()
        if len(response.text) < 1000:
            raise RuntimeError(f"unexpectedly short Prilla page: {url}")
        self.cache[url] = response.text
        return response.text


def discover_categories(fetcher):
    paths = list(FALLBACK_CATEGORIES)
    seen = set(paths)
    html = fetcher.get(BASE + US_ROOT)
    soup = BeautifulSoup(html, "lxml")
    for anchor in soup.select("nav a[href], header a[href], footer a[href]"):
        url = canonical_url(anchor.get("href"))
        path = urlsplit(url).path.rstrip("/")
        if path.startswith(US_ROOT + "/") and path not in seen and len(path.split("/")) == 3:
            seen.add(path)
            paths.append(path)
    # The sitemap is the authoritative additive fallback for categories that
    # are not currently visible in the navigation.
    try:
        sitemap = fetcher.session.get(BASE + "/us/sitemap_us.xml", headers=HEADERS, timeout=REQUEST_TIMEOUT)
        sitemap.raise_for_status()
        for loc in BeautifulSoup(sitemap.text, "xml").select("url > loc"):
            path = urlsplit(loc.get_text(strip=True)).path.rstrip("/")
            if path.startswith(US_ROOT + "/") and len(path.split("/")) == 3 and path not in seen:
                seen.add(path)
                paths.append(path)
    except requests.RequestException as error:
        print(f"Prilla sitemap discovery unavailable: {error}")
    return prioritize_links(paths)


def parse_card(card, category):
    link = card.select_one("a.product-item-name[href]")
    if not link:
        href = card.select_one("[data-href]")
        url = href.get("data-href") if href else None
    else:
        url = link.get("href")
    url = canonical_url(url)
    path = urlsplit(url).path
    if not url or not path.startswith(US_ROOT + "/") or len(path.split("/")) < 4:
        return None
    image = card.select_one("img[data-src], img[src]")
    prices = [money(node.get_text(" ", strip=True)) for node in card.select(".price")]
    prices = [value for value in prices if value]
    return {
        "url": url, "tag": product_tag(url),
        "title": clean(link.get_text(" ", strip=True)) if link else product_tag(url),
        "brand": "", "regular_price": prices[-1] if prices else None,
        "sale_price": prices[0] if len(prices) > 1 else None,
        "stock_status": "In Stock" if card.get("data-stock") == "true" else "Out of Stock",
        "image": (image.get("data-src") or image.get("src")) if image else None,
        "site_category": normalize_site_category(category),
    }


def structured_product(soup):
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(script.string or script.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        values = value if isinstance(value, list) else [value]
        for item in values:
            if isinstance(item, dict) and item.get("@type") == "Product":
                return item
    return {}


def image_candidates(soup, structured):
    values = structured.get("image", [])
    values = values if isinstance(values, list) else [values]
    values += [node.get("src") or node.get("data-src") for node in soup.select(
        ".product.media img, .gallery-placeholder img, meta[property='og:image']")]
    result, seen = [], set()
    for value in values:
        if hasattr(value, "get"):
            value = value.get("content")
        value = urljoin(BASE, value or "")
        if value and value not in seen and not any(word in value.lower() for word in ("logo", "icon", "placeholder")):
            seen.add(value)
            result.append({"url": value, "alt": structured.get("name", "")})
    return result


def parse_product(html, card):
    soup = BeautifulSoup(html, "lxml")
    structured = structured_product(soup)
    form = soup.select_one("form#product_addtocart_form")
    title = structured.get("name") or clean(soup.select_one("h1.page-title").get_text() if soup.select_one("h1.page-title") else card["title"])
    description = clean(soup.select_one(".product.attribute.description").get_text(" ", strip=True) if soup.select_one(".product.attribute.description") else structured.get("description", ""))
    combined = "\n".join((description, soup.get_text(" ", strip=True)))
    _, puffs, nicotine, liquid, flavors, devices = find_features(combined)
    price_meta = soup.select_one("meta[property='product:price:amount']")
    price_value = price_meta.get("content") if price_meta else None
    if not price_value:
        prices = [money(node.get_text(" ", strip=True)) for node in soup.select(".price")]
        price_value = next((value for value in prices if value), card["regular_price"])
    regular = card["regular_price"] or price_value
    sale = card["sale_price"] if card["sale_price"] and card["sale_price"] != regular else None
    stock = "Out of Stock" if soup.select_one("button.notify, .stock.unavailable") else card["stock_status"]
    sku = structured.get("sku") or (form.get("data-product-sku") if form else None)
    brand = structured.get("brand", {})
    brand = brand.get("name") if isinstance(brand, dict) else brand
    return {
        "title": title, "brand": brand or card["brand"], "link": card["url"],
        "site_category": card["site_category"], "tag": card["tag"], "sku": sku,
        "regular_price": regular or price_value, "sale_price": sale,
        "flavor_text": ", ".join(dict.fromkeys(flavors or [])), "description": description,
        "package_contents": "", "features": ", ".join(dict.fromkeys(devices or [])),
        "ingredients": "", "warnings": "", "eliquid_contents": liquid, "puffs": puffs,
        "coil": "", "battery": extract_battery(combined), "power_level": "",
        "nicotine_strength": nicotine, "stock_status": stock,
        "reviews": extract_reviews(soup), "review_attributes": {}, "flavor_list": [],
        "nicotine_strengths": [], "image_urls": image_candidates(soup, structured),
        "html": html, "plain_text": soup.get_text(" ", strip=True),
    }


def main(sample=False, write_db=WRITE_DB):
    fetcher = Fetcher()
    seen, processed = set(), 0
    categories = FALLBACK_CATEGORIES[:1] if sample else discover_categories(fetcher)
    for category in categories:
        for page in range(1, MAX_PAGES + 1):
            listing_url = f"{BASE}{category}?page={page}" if page > 1 else BASE + category
            try:
                soup = BeautifulSoup(fetcher.get(listing_url), "lxml")
            except Exception as error:
                print(f"SKIP listing {listing_url}: {error}")
                break
            cards = [parse_card(node, category) for node in soup.select("li.product-item")]
            cards = [card for card in cards if card and card["tag"] not in seen]
            print(f"{SITE} {listing_url}: {len(cards)} new cards")
            if not cards:
                break
            for card in cards:
                if MAX_PRODUCTS and processed >= MAX_PRODUCTS:
                    return
                seen.add(card["tag"])
                try:
                    data = parse_product(fetcher.get(card["url"]), card)
                    if sample or not write_db:
                        print(f"SAMPLE {data['tag']}: {data['title']} [{data['stock_status']}]")
                        processed += 1
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
                    processed += 1
                except Exception as error:
                    print(f"SKIP product {card['url']}: {error}")


if __name__ == "__main__":
    main(sample=os.getenv("PRILLA_SAMPLE", "0").lower() in {"1", "true", "yes"})
