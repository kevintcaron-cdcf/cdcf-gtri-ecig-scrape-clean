"""Nicokick USA Magento/Hyva catalog scraper."""

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
    NICOKICK,
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

BASE = "https://nicokick.com"
SITEMAP_URL = BASE + "/media/sitemap_categories.xml"
SITE = NICOKICK
REQUEST_TIMEOUT = 45
REQUEST_DELAY = float(os.getenv("NICOKICK_REQUEST_DELAY", "1.5"))
MAX_PAGES = int(os.getenv("NICOKICK_MAX_PAGES", "100"))
MAX_PRODUCTS = int(os.getenv("NICOKICK_MAX_PRODUCTS", "0"))
WRITE_DB = os.getenv("SCRAPE_WRITE_DB", "1").lower() in {"1", "true", "yes"}
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CDCFResearch/1.0)"}
FALLBACK_CATEGORIES = [
    "/us/nicotine-pouches/new-arrivals",
    "/us/nicotine-pouches",
    "/us/nicotine-pouches/bestsellers-nicotine-pouches",
    "/us/nicotine-pouches/zyn",
    "/us/nicotine-pouches/velo",
    "/us/nicotine-pouches/on",
    "/us/nicotine-pouches/rogue",
    "/us/nicotine-pouches/low-nicotine-strength",
    "/us/nicotine-pouches/normal-nicotine-strength",
    "/us/nicotine-pouches/strong-nicotine-strength",
    "/us/nicotine-pouches/extra-nicotine-strength",
    "/us/nicotine-gum",
    "/us/nicotine-lozenges",
    "/us/other-products",
]
BLOCK_MARKERS = ("access denied", "verify you are human", "captcha", "challenge")


def canonical_url(value):
    parts = urlsplit(urljoin(BASE, value or ""))
    query = [(key, val) for key, val in parse_qsl(parts.query) if key in {"p", "page"}]
    return urlunsplit(("https", parts.netloc or "nicokick.com", parts.path.rstrip("/") or "/",
                       urlencode(query), ""))


def product_tag(url):
    return urlsplit(canonical_url(url)).path.rstrip("/").split("/")[-1]


def clean(value):
    if hasattr(value, "get_text"):
        value = value.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", BeautifulSoup(str(value or ""), "lxml").get_text(" ", strip=True)).strip()


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
            raise RuntimeError(f"Nicokick access/rate-limit response {response.status_code}: {url}")
        response.raise_for_status()
        if len(response.text) < 1000:
            raise RuntimeError(f"unexpectedly short Nicokick page: {url}")
        self.cache[url] = response.text
        return response.text


def discover_categories(fetcher):
    paths, seen = list(FALLBACK_CATEGORIES), set(FALLBACK_CATEGORIES)
    try:
        xml = fetcher.session.get(SITEMAP_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        xml.raise_for_status()
        for loc in BeautifulSoup(xml.text, "xml").select("url > loc"):
            path = urlsplit(loc.get_text(strip=True)).path.rstrip("/")
            if (
                path.startswith("/us/")
                and "//" not in path
                and path not in {"/us/learn-more", "/us/default-category"}
                and path not in seen
            ):
                seen.add(path)
                paths.append(path)
    except requests.RequestException as error:
        print(f"Nicokick category sitemap unavailable: {error}")
    return prioritize_links(paths)


def parse_card(card, category):
    link = card.select_one("a.product-item-link[href]")
    if not link:
        return None
    url = canonical_url(link.get("href"))
    if not urlsplit(url).path.startswith("/us/"):
        return None
    image = card.select_one("img[src], img[data-src]")
    prices = [money(node.get_text(" ", strip=True)) for node in card.select(".product-card-price, .price")]
    prices = [value for value in prices if value]
    return {
        "url": url, "tag": product_tag(url), "title": clean(link.get("aria-label") or link.get_text()),
        "brand": clean(card.select_one(".product-card-brand").get_text() if card.select_one(".product-card-brand") else ""),
        "regular_price": prices[0] if prices else None, "sale_price": None,
        "stock_status": "Out of Stock" if "out of stock" in clean(card).lower() else "In Stock",
        "image": (image.get("data-src") or image.get("src")) if image else None,
        "site_category": normalize_site_category(category),
    }


def structured_product(soup):
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(script.string or script.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        values = value.get("@graph", []) if isinstance(value, dict) and "@graph" in value else [value]
        for item in values:
            if isinstance(item, dict) and item.get("@type") == "Product":
                return item
    return {}


def image_candidates(soup, structured):
    values = structured.get("image", [])
    values = values if isinstance(values, list) else [values]
    values += [node.get("content") or node.get("src") or node.get("data-src") for node in soup.select(
        ".pdp-gallery-wrapper img, #productMedia img, link[rel='preload'][as='image'], meta[property='og:image']")]
    result, seen = [], set()
    for value in values:
        value = urljoin(BASE, value or "")
        if value and value not in seen and not any(word in value.lower() for word in ("logo", "icon", "placeholder")):
            seen.add(value)
            result.append({"url": value, "alt": structured.get("name", "")})
    return result


def parse_product(html, card):
    soup = BeautifulSoup(html, "lxml")
    structured = structured_product(soup)
    offer = structured.get("offers", {})
    title = structured.get("name") or clean(soup.select_one("h1.pdp-title").get_text() if soup.select_one("h1.pdp-title") else card["title"])
    description_node = soup.select_one(".accordion-tab-content")
    description = clean(description_node.get_text(" ", strip=True) if description_node else structured.get("description", ""))
    combined = "\n".join((description, soup.get_text(" ", strip=True)))
    _, puffs, nicotine, liquid, flavors, devices = find_features(combined)
    measurement = structured.get("hasMeasurement", {})
    if measurement.get("value") and not nicotine:
        nicotine = f"{measurement['value']} {measurement.get('unitText', 'mg') }"
    price_value = money(offer.get("price")) or card["regular_price"]
    availability = str(offer.get("availability", ""))
    stock = "Out of Stock" if "OutOfStock" in availability or "out of stock" in combined.lower() else "In Stock"
    brand = card["brand"]
    for crumb in soup.select(".breadcrumbs-container a"):
        value = clean(crumb.get_text())
        if value and value.lower() not in {"nicokick", "nicotine pouches"}:
            brand = value
            break
    return {
        "title": title, "brand": brand, "link": card["url"], "site_category": card["site_category"],
        "tag": card["tag"], "sku": next((item.get("sku") for item in structured.get("isVariantOf", {}).get("hasVariant", []) if item.get("name") == title), None),
        "regular_price": price_value, "sale_price": None, "flavor_text": ", ".join(dict.fromkeys(flavors or [])),
        "description": description, "package_contents": "", "features": ", ".join(dict.fromkeys(devices or [])),
        "ingredients": "", "warnings": "", "eliquid_contents": liquid, "puffs": puffs, "coil": "",
        "battery": extract_battery(combined), "power_level": "", "nicotine_strength": nicotine,
        "stock_status": stock, "reviews": extract_reviews(soup), "review_attributes": {}, "flavor_list": [],
        "nicotine_strengths": [], "image_urls": image_candidates(soup, structured), "html": html,
        "plain_text": soup.get_text(" ", strip=True),
    }


def main(sample=False, write_db=WRITE_DB):
    fetcher = Fetcher()
    seen, processed = set(), 0
    categories = FALLBACK_CATEGORIES[:1] if sample else discover_categories(fetcher)
    for category in categories:
        page_signatures = set()
        duplicate_pages = 0
        for page in range(1, MAX_PAGES + 1):
            listing_url = f"{BASE}{category}?p={page}" if page > 1 else BASE + category
            try:
                soup = BeautifulSoup(fetcher.get(listing_url), "lxml")
            except requests.HTTPError as error:
                # Magento often redirects an exhausted category page to its
                # canonical URL before returning 404.  That is a normal end
                # of pagination, not an access failure.
                if error.response is not None and error.response.status_code == 404:
                    print(f"END pagination {listing_url}: HTTP 404")
                    break
                print(f"SKIP listing {listing_url}: {error}")
                break
            except Exception as error:
                print(f"SKIP listing {listing_url}: {error}")
                break
            raw_cards = [parse_card(node, category) for node in soup.select("form.product-card")]
            raw_cards = [card for card in raw_cards if card]
            page_signature = tuple(card["tag"] for card in raw_cards)
            if page_signature in page_signatures:
                print(f"END pagination {listing_url}: repeated product page")
                break
            page_signatures.add(page_signature)
            cards = raw_cards
            cards = [card for card in cards if card and card["tag"] not in seen]
            print(f"{SITE} {listing_url}: {len(raw_cards)} cards, {len(cards)} new")
            if not raw_cards:
                break
            if not cards:
                duplicate_pages += 1
                if duplicate_pages >= 1:
                    print(f"END pagination {listing_url}: no new products")
                    break
            else:
                duplicate_pages = 0
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
    main(sample=os.getenv("NICOKICK_SAMPLE", "0").lower() in {"1", "true", "yes"})
