"""Shared conservative BigCommerce listing/detail scraper helpers."""

import os
import re
import sys
import time
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup, element

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from db.db_azure import get_product_id, insert_ecig_price, insert_product_images, insert_reviews, map_product_data, product_has_images, sync_ecig_product_history  # noqa: E402
from ecig_parsing import download_image_batch, extract_battery, extract_reviews, find_features, normalize_site_category, prioritize_links  # noqa: E402

REQUEST_TIMEOUT = 45
MAX_PAGES = 100
DELAY = 2


def request_url(base, url):
    parts = urlsplit(urljoin(base, url))
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), parts.query, ""))


def text(node):
    return node.get_text(" ", strip=True) if node else ""


def price(value):
    match = re.search(r"\d+(?:,\d{3})*(?:\.\d{2})?", value or "")
    return match.group(0).replace(",", "") if match else None


def card_price(card):
    values = [
        card.get("data-product-price"),
        card.get("data-product-price-without-tax"),
        card.get("data-product-price-with-tax"),
    ]
    values.extend(
        text(node)
        for node in card.select(
            ".price, .price-section, [data-product-price-without-tax], "
            "[data-product-price-with-tax], .card-text[data-test-info-type='price'], "
            ".product-card-price, .price-box"
        )
    )
    return next((parsed for value_text in values if (parsed := price(value_text))), None)


def cards(soup):
    return soup.select("ul.productGrid article.card, article.card, li.product")


def discover_categories(session, config):
    """Discover current catalog links from the retailer's navigation."""
    homepage = session.get(config["base"], timeout=REQUEST_TIMEOUT)
    homepage.raise_for_status()
    soup = BeautifulSoup(homepage.text, "lxml")
    discovered = []
    seen = set()
    excluded_parts = {
        "/cart", "/login", "/account", "/compare", "/wishlist", "/search",
        "/contact", "/privacy", "/terms", "/blog", "/pages/",
    }
    for link in soup.select("nav a[href], header a[href], .navPages a[href]"):
        href = link.get("href", "").strip()
        absolute = request_url(config["base"], href)
        path = urlsplit(absolute).path.rstrip("/")
        lower_path = path.lower()
        if not path or absolute in seen or "/products/" in lower_path:
            continue
        if any(part in lower_path for part in excluded_parts):
            continue
        seen.add(absolute)
        discovered.append(path)
    combined = list(config.get("links", []))
    for path in discovered:
        if path not in combined:
            combined.append(path)
    print(f"{config['name']} discovered {len(discovered)} navigation categories; using {len(combined)} total categories")
    return prioritize_links(combined)


def parse_card(card, base):
    link = card.select_one(
        'a[href*="/products/"], a.card-title[href], '
        'h3.card-title a[href], h4.card-title a[href]'
    )
    if not link:
        link = next(
            (
                candidate
                for candidate in card.select("a[href]")
                if not any(part in candidate.get("href", "").lower() for part in ("cart.php", "login.php", "compare"))
            ),
            None,
        )
    title = card.select_one(".card-title, [data-test-info-type='productName']")
    if not link or not title:
        return None
    url = request_url(base, link.get("href"))
    return {"url": url, "tag": urlsplit(url).path.rstrip("/").split("/")[-1], "title": text(title), "brand": text(card.select_one('[data-test-info-type="brandName"]')), "price": card_price(card)}


def parse_product(card, html, category, base, site):
    soup = BeautifulSoup(html, "lxml")
    description = text(soup.select_one(".productView-description, .product-description"))
    combined = "\n".join((description, soup.get_text(" ", strip=True)))
    _, puffs, nicotine, liquid, _, _ = find_features(combined)
    image_candidates, seen_urls = [], set()
    gallery = soup.select_one(".productView-images") or soup
    for number, image in enumerate(gallery.select("img"), start=1):
        src = image.get("data-zoom-image") or image.get("data-src") or image.get("src")
        if not src and image.get("srcset"):
            src = image.get("srcset").split(",")[-1].strip().split(" ")[0]
        if not src:
            continue
        src = urljoin(base, src)
        if src in seen_urls or "logo" in src.lower() or src.startswith("data:"):
            continue
        seen_urls.add(src)
        image_candidates.append({'url': src, 'alt': image.get('alt', '')})
    images = download_image_batch(
        image_candidates, card["tag"], f"data_from_sites_v2/{site}_images"
    )
    meta_price = soup.select_one('meta[property="product:price:amount"]')
    detail_price = price(text(soup.select_one("[data-product-price-without-tax], [data-product-price-with-tax], .productView-price, .price")))
    if not detail_price and meta_price:
        detail_price = price(meta_price.get("content", ""))
    return {"title": text(soup.select_one("h1.productView-title")) or card["title"], "link": card["url"], "site_category": normalize_site_category(category), "tag": card["tag"], "brand": text(soup.select_one("h2.productView-brand")) or card["brand"], "html": html, "plain_text": soup.get_text(" ", strip=True), "regular_price": detail_price or card["price"], "sale_price": None, "flavor_text": "", "description": description, "package_contents": "", "features": "", "ingredients": "", "warnings": "", "eliquid_contents": liquid, "puffs": puffs, "coil": "", "battery": extract_battery(combined), "power_level": "", "nicotine_strength": nicotine, "stock_status": "", "reviews": extract_reviews(soup), "review_attributes": {}, "flavor_list": [], "nicotine_strengths": [], "images": images}


def run(config):
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/121 Safari/537.36"
    found, last_request = {}, 0
    for category in discover_categories(session, config):
        for page in range(1, MAX_PAGES + 1):
            url = request_url(config["base"], category) + (f"?page={page}" if page > 1 else "")
            wait = DELAY - (time.time() - last_request)
            if wait > 0:
                time.sleep(wait)
            response = session.get(url, timeout=REQUEST_TIMEOUT)
            last_request = time.time()
            if response.status_code == 404:
                print(f"SKIP category page 404: {url}")
                break
            try:
                response.raise_for_status()
            except requests.RequestException as error:
                print(f"SKIP category page fetch failed: {error}")
                break
            found[url] = response.text
            product_cards = cards(BeautifulSoup(response.text, "lxml"))
            print(f"{config['name']} {url}: {len(product_cards)} cards")
            if not product_cards:
                break
            for node in product_cards:
                if not isinstance(node, element.Tag):
                    continue
                card = parse_card(node, config["base"])
                if not card or card["url"] in found:
                    if not card:
                        print(f"SKIP card: unable to extract product link/title on {url}")
                    continue
                detail = session.get(card["url"], timeout=REQUEST_TIMEOUT)
                if detail.status_code == 404:
                    print(f"SKIP {card['tag']}: product page returned 404")
                    found[card["url"]] = detail.text
                    continue
                try:
                    detail.raise_for_status()
                except requests.RequestException as error:
                    print(f"SKIP {card['tag']}: product fetch failed: {error}")
                    continue
                found[card["url"]] = detail.text
                product_id = get_product_id(config["site"], card["tag"])
                print(f"PRODUCT {card['title']} [{card['tag']}] {'EXISTS' if product_id else 'NEW'}")
                if product_id:
                    insert_ecig_price(product_id, card["price"], None)
                    data = parse_product(card, detail.text, category, config["base"], config["name"])
                    sync_ecig_product_history(product_id, data)
                    print(f"REVIEWS {card['tag']}: {len(data['reviews'])} found" if data["reviews"] else f"REVIEWS {card['tag']}: none found")
                    if data["reviews"]:
                        insert_reviews(data["reviews"], product_id)
                    if not product_has_images(product_id):
                        insert_product_images(product_id, data["images"])
                    else:
                        print(f"IMAGES EXIST for product_id {product_id}; skipping image download")
                else:
                    data = parse_product(card, detail.text, category, config["base"], config["name"])
                    print(f"REVIEWS {card['tag']}: {len(data['reviews'])} found" if data["reviews"] else f"REVIEWS {card['tag']}: none found")
                    print(f"Downloaded {len(data['images'])} images for {card['tag']}")
                    map_product_data(config["site"], data)
            if page >= MAX_PAGES:
                print(f"PAGE LIMIT REACHED for {category}")
                break
