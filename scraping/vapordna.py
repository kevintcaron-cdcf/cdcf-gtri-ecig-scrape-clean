"""VaporDNA Shopify scraper.

VaporDNA exposes Shopify's public product JSON endpoint.  The scraper uses
that endpoint for discovery and the product HTML page as the authoritative
source for the stored HTML and description.
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from db.db_azure import (  # noqa: E402
    VAPOR_DNA,
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
    find_features,
    normalize_site_category,
    prioritize_links,
)


BASE = "https://vapordna.com"
PRODUCTS_PER_PAGE = 250
MAX_PAGES = 20
REQUEST_DELAY = 1.5
REQUEST_TIMEOUT = 45
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CDCFResearch/1.0)"}
FALLBACK_COLLECTIONS = [
    "/collections/all",
    "/collections/new-arrivals",
    "/collections/disposable-vapes",
    "/collections/e-liquids",
    "/collections/pod-systems",
    "/collections/vape-mods",
    "/collections/vape-tanks",
    "/collections/accessories",
]


def canonical_url(value):
    url = urljoin(BASE, value or "")
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def product_tag(url):
    return urlsplit(canonical_url(url)).path.rstrip("/").split("/")[-1]


def money(value):
    if value is None:
        return None
    match = re.search(r"\d+(?:,\d{3})*(?:\.\d{1,2})?", str(value))
    return match.group(0).replace(",", "") if match else None


def get_json(session, url):
    response = session.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def discover_collections(session):
    """Merge fallback categories with the current collection sitemap."""
    links = list(FALLBACK_COLLECTIONS)
    try:
        homepage = session.get(BASE, timeout=REQUEST_TIMEOUT)
        homepage.raise_for_status()
        homepage_soup = BeautifulSoup(homepage.text, "lxml")
        for anchor in homepage_soup.select('a[href*="/collections/"]'):
            path = urlsplit(canonical_url(anchor.get("href"))).path
            if path.startswith("/collections/") and path not in links:
                links.append(path)
    except requests.RequestException as error:
        print(f"Homepage collection discovery unavailable; using fallback categories: {error}")
    return prioritize_links(links)


def listing_products(session, collection, page):
    url = f"{BASE}{collection}/products.json?limit={PRODUCTS_PER_PAGE}&page={page}"
    payload = get_json(session, url)
    return payload.get("products", [])


def product_from_listing(product, collection):
    handle = product.get("handle")
    if not handle:
        return None
    url = canonical_url(f"/products/{handle}")
    variants = product.get("variants") or []
    first = variants[0] if variants else {}
    return {
        "url": url,
        "tag": product_tag(url),
        "title": product.get("title", "").strip(),
        "brand": product.get("vendor", "").strip(),
        "regular_price": money(first.get("compare_at_price")) or money(first.get("price")),
        "sale_price": money(first.get("price")) if first.get("compare_at_price") else None,
        "site_category": normalize_site_category(collection),
        "listing": product,
    }


def json_ld_product(soup):
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


def review_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def nicotine_level(value):
    """Convert a simple Shopify nicotine option to the SQL numeric contract."""
    value = str(value or "").strip()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(mg(?:/ml)?|%)", value, re.I)
    if not match:
        return None
    return {
        "value": float(match.group(1)),
        "unit": match.group(2),
        "level": None,
    }


def parse_reviews(soup, structured):
    """Extract Judge.me reviews from the SSR JSON-LD and review cards."""
    reviews = []
    seen = set()

    def add_review(author, body, rating, date=None, verified=False, variant=None):
        body = (body or "").strip()
        if not body:
            return
        review = {
            "date": review_date(date),
            "author": (author or "").strip() or None,
            "rating": rating,
            "verified_buyer": bool(verified),
            "review_text": body,
            "variant": variant,
        }
        key = (review["author"], review["review_text"], review["date"])
        if key not in seen:
            seen.add(key)
            reviews.append(review)

    for item in structured.get("review", []) if isinstance(structured.get("review"), list) else []:
        author = item.get("author", {})
        author = author.get("name") if isinstance(author, dict) else author
        rating = item.get("reviewRating", {})
        rating = rating.get("ratingValue") if isinstance(rating, dict) else rating
        try:
            rating = float(rating) if rating is not None else None
        except (TypeError, ValueError):
            rating = None
        add_review(author, item.get("reviewBody"), rating, item.get("datePublished"))

    for item in soup.select(".jdgm-rev[data-review-id]"):
        rating_node = item.select_one(".jdgm-rev__rating")
        rating = rating_node.get("data-score") if rating_node else None
        try:
            rating = float(rating) if rating is not None else None
        except (TypeError, ValueError):
            rating = None
        author_node = item.select_one(".jdgm-rev__author")
        body_node = item.select_one(".jdgm-rev__body")
        date_node = item.select_one(".jdgm-rev__timestamp")
        variant_node = item.select_one(".jdgm-rev__prod-info")
        add_review(
            author_node.get_text(" ", strip=True) if author_node else None,
            body_node.get_text(" ", strip=True) if body_node else None,
            rating,
            date_node.get("datetime") if date_node else None,
            item.get("data-verified-buyer") == "true",
            variant_node.get_text(" ", strip=True) if variant_node else None,
        )
    return reviews


def parse_product(card, html, download_images=True):
    soup = BeautifulSoup(html, "lxml")
    listing = card["listing"]
    structured = json_ld_product(soup)
    title = structured.get("name") or card["title"] or (soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else "")
    plain_text = soup.get_text(" ", strip=True)
    description_html = listing.get("body_html") or structured.get("description") or ""
    description = BeautifulSoup(description_html, "lxml").get_text(" ", strip=True)
    combined = "\n".join((description, plain_text))
    _, puffs, nicotine, liquid, _, _ = find_features(combined)

    variants = listing.get("variants") or []
    nicotine_levels = []
    for variant in variants:
        value = variant.get("title") or variant.get("option1")
        if value and re.search(r"(?:mg|%|nicotine)", value, re.I):
            parsed_level = nicotine_level(value)
            if parsed_level:
                nicotine_levels.append(parsed_level)
    images = []
    seen = set()
    for image in listing.get("images", []):
        image_url = image.get("src") if isinstance(image, dict) else image
        image_url = urljoin(BASE, image_url or "")
        if image_url and image_url not in seen and "logo" not in image_url.lower():
            seen.add(image_url)
            images.append({"url": image_url, "alt": title})
    saved_images = download_image_batch(images, card["tag"], f"data_from_sites_v2/{VAPOR_DNA}_images") if download_images else []
    return {
        "title": title,
        "brand": structured.get("brand", {}).get("name", card["brand"]) if isinstance(structured.get("brand", {}), dict) else card["brand"],
        "link": card["url"],
        "site_category": card["site_category"],
        "tag": card["tag"],
        "html": html,
        "plain_text": plain_text,
        "regular_price": card["regular_price"],
        "sale_price": card["sale_price"],
        "flavor_text": "",
        "description": description,
        "package_contents": "",
        "features": "",
        "ingredients": "",
        "warnings": "",
        "eliquid_contents": liquid,
        "puffs": puffs,
        "coil": "",
        "battery": extract_battery(combined),
        "power_level": "",
        "nicotine_strength": nicotine,
        "stock_status": "In Stock" if any(v.get("available") for v in variants) else "Out of Stock",
        "reviews": parse_reviews(soup, structured),
        "review_attributes": {},
        "flavor_list": [],
        "nicotine_strengths": nicotine_levels,
        "images": saved_images,
    }


def main(sample=False):
    session = requests.Session()
    session.headers.update(HEADERS)
    found = {}
    seen_tags = set()
    collections = discover_collections(session)
    if sample:
        collections = ["/collections/all"]
    last_request = 0
    for collection in collections:
        for page in range(1, MAX_PAGES + 1):
            wait = REQUEST_DELAY - (time.monotonic() - last_request)
            if wait > 0:
                time.sleep(wait)
            try:
                products = listing_products(session, collection, page)
            except (requests.RequestException, ValueError) as error:
                print(f"SKIP listing {collection} page {page}: {error}")
                break
            last_request = time.monotonic()
            print(f"VAPOR DNA {collection} page {page}: {len(products)} products")
            if not products:
                break
            for raw_product in products:
                card = product_from_listing(raw_product, collection)
                if not card or card["tag"] in seen_tags:
                    continue
                seen_tags.add(card["tag"])
                if card["url"] in found:
                    html = found[card["url"]]
                else:
                    try:
                        response = session.get(card["url"], timeout=REQUEST_TIMEOUT)
                        response.raise_for_status()
                        html = found[card["url"]] = response.text
                    except requests.RequestException as error:
                        print(f"SKIP {card['tag']}: product fetch failed: {error}")
                        continue
                if sample:
                    print(f"SAMPLE {card['tag']}: {card['title']}")
                    print(f"SAMPLE FIELDS: {sorted(parse_product(card, html).keys())}")
                    return
                product_id = get_product_id(VAPOR_DNA, card["tag"])
                print(f"PRODUCT {card['title']} [{card['tag']}] {'EXISTS' if product_id else 'NEW'}")
                data = parse_product(card, html, download_images=not product_id)
                print(f"REVIEWS {card['tag']}: {len(data['reviews'])} found" if data["reviews"] else f"REVIEWS {card['tag']}: none found")
                if product_id:
                    insert_ecig_price(product_id, card["regular_price"], card["sale_price"])
                    sync_ecig_product_history(product_id, data)
                    if data["reviews"]:
                        insert_reviews(data["reviews"], product_id)
                    if not product_has_images(product_id):
                        data = parse_product(card, html, download_images=True)
                        insert_product_images(product_id, data["images"])
                else:
                    map_product_data(VAPOR_DNA, data)
            if sample:
                return


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape VaporDNA Shopify products")
    parser.add_argument("--sample", action="store_true", help="parse one product without database writes")
    main(sample=parser.parse_args().sample)
