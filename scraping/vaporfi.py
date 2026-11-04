"""VaporFi Shopware 6 catalog scraper."""

import os
import random
import re
import sys
import time
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup, element

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from db.db_azure import (  # noqa: E402
    VAPORFI,
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

BASE = "https://www.vaporfi.com"
SITE = VAPORFI
REQUEST_TIMEOUT = 45
MAX_PAGES = int(os.getenv("VAPORFI_MAX_PAGES", "100"))
MAX_PRODUCTS = int(os.getenv("VAPORFI_MAX_PRODUCTS", "0"))
DELAY = float(os.getenv("VAPORFI_DELAY", "2"))
LINKS = [
    "/whats-new/", "/disposable-vapes/", "/cartridges/", "/vape-pens/",
    "/starter-kits/", "/vape-juice/", "/vape-accessories/", "/pouches/",
    "/clearance/", "/toke-dab/", "/vape-brands/",
]


def canonical_url(value):
    url = urljoin(BASE, value or "")
    parts = urlsplit(url)
    query = [(key, val) for key, val in parse_qsl(parts.query) if key == "p"]
    return urlunsplit((parts.scheme or "https", parts.netloc or urlsplit(BASE).netloc,
                       parts.path.rstrip("/") or "/", urlencode(query), ""))


def tag_for(url):
    return urlsplit(canonical_url(url)).path.rstrip("/").split("/")[-1]


def text(node):
    return node.get_text(" ", strip=True) if node else ""


def first_text(soup, selectors):
    for selector in selectors:
        node = soup.select_one(selector)
        if text(node):
            return text(node)
    return ""


def price(value):
    match = re.search(r"\d+(?:[,.]\d{3})*(?:[,.]\d{2})?", value or "")
    return match.group(0).replace(",", "") if match else None


def page_url(url, page):
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    if page > 1:
        query["p"] = str(page)
    else:
        query.pop("p", None)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def is_blocked(response):
    body = response.text[:100000].lower()
    return response.status_code in {403, 429} or any(
        marker in body for marker in ("verify you are human", "access denied", "challenge required")
    )


def fetch(session, url, cache, last_request):
    url = canonical_url(url)
    if url in cache:
        return cache[url], last_request
    wait = DELAY - (time.monotonic() - last_request)
    if wait > 0:
        time.sleep(wait + random.uniform(0, min(0.75, wait * 0.25)))
    response = session.get(url, timeout=REQUEST_TIMEOUT)
    last_request = time.monotonic()
    if is_blocked(response):
        raise RuntimeError(f"access/rate-limit response {response.status_code}: {url}")
    response.raise_for_status()
    if len(response.text) < 1000:
        raise RuntimeError(f"unexpectedly short page: {url}")
    cache[url] = response.text
    return response.text, last_request


def discover_categories(session, cache, last_request):
    html, last_request = fetch(session, BASE, cache, last_request)
    soup = BeautifulSoup(html, "lxml")
    paths, seen = list(LINKS), set(LINKS)
    excluded = ("/account", "/customer-service", "/checkout", "/wishlist", "/blog",
                "/privacy", "/terms", "/search", "/our-company", "/learn", "/how-it-works")
    catalog_roots = ("/vape-juice", "/disposable-vapes", "/cartridges", "/vape-pens",
                     "/starter-kits", "/toke-dab", "/vape-accessories", "/pouches",
                     "/clearance", "/vape-brands", "/whats-new")
    for link in soup.select("nav a[href], header a[href], footer a[href]"):
        url = canonical_url(link.get("href"))
        path = urlsplit(url).path.rstrip("/") or "/"
        if urlsplit(url).netloc != urlsplit(BASE).netloc or path == "/":
            continue
        if any(part in path.lower() for part in excluded) or not path.startswith(catalog_roots):
            continue
        if path not in seen:
            seen.add(path)
            paths.append(path + "/")
    return prioritize_links(paths), last_request


def parse_card(card):
    if not isinstance(card, element.Tag):
        return None
    link = card.select_one("a.product-image-link[href], a.product-name[href]")
    if not link:
        return None
    url = canonical_url(link.get("href"))
    if urlsplit(url).netloc != urlsplit(BASE).netloc or tag_for(url) in {"", "www.vaporfi.com"}:
        return None
    title = first_text(card, ("a.product-name", "a.product-image-link[title]")) or link.get("title", "")
    if not title:
        return None
    image = card.select_one("img.product-image, .product-image-wrapper img")
    return {"url": url, "tag": tag_for(url), "title": title,
            "brand": first_text(card, (".product-brand", ".brand")),
            "price": price(text(card.select_one(".product-price"))),
            "image": image.get("src") if image else None}


def image_candidates(soup):
    candidates, seen = [], set()
    for node in soup.select(".product-detail-media img, .product-detail-media a[href]"):
        if node.name == "a":
            source, alt = node.get("href"), ""
        else:
            source, alt = node.get("data-zoom-image") or node.get("src"), node.get("alt", "")
            if node.get("srcset") or node.get("data-srcset"):
                source = (node.get("srcset") or node.get("data-srcset")).split(",")[-1].strip().split(" ")[0]
        source = urljoin(BASE, source or "")
        if not source or source.startswith("data:") or source in seen:
            continue
        if any(word in source.lower() for word in ("logo", "icon", "placeholder")):
            continue
        seen.add(source)
        candidates.append({"url": source, "alt": alt})
    return candidates


def parse_product(html, card, category):
    soup = BeautifulSoup(html, "lxml")
    root = soup.select_one(".product-detail-buy") or soup
    title = first_text(root, ('[itemprop="name"]', "h1.product-name")) or card["title"]
    description = first_text(root, ('[itemprop="description"]', ".product-description"))
    brand = first_text(root, ('[itemprop="brand"] [itemprop="name"]', ".brands a")) or card["brand"]
    sku_node = root.select_one('[itemprop="sku"]')
    sku = (sku_node.get("content") if sku_node else None) or text(sku_node)
    price_node = root.select_one('[itemprop="price"]')
    regular_price = price(price_node.get("content") if price_node else "") or card["price"]
    visible_price = price(first_text(root, (".product-detail-price",)))
    sale_price = visible_price if regular_price and visible_price and visible_price != regular_price else None
    combined = "\n".join((description, soup.get_text(" ", strip=True)))
    _, puffs, nicotine, liquid, flavors, devices = find_features(combined)
    option_values = []
    for option in soup.select(".product-detail-configurator-option-label, .product-detail-configurator-option-input"):
        value = option.get("title") or text(option)
        if value and value.lower() not in {"choose", "select", "option"} and value not in option_values:
            option_values.append(value)
    stock_text = first_text(soup, (".product-detail-delivery-information", ".product-delivery-information"))
    if soup.select_one("#productDetailPageBackInStockForm, #back-in-stock-modal") or re.search(r"notify me|coming soon|back in stock", stock_text, re.I):
        stock_status = "Out of Stock"
    elif soup.select_one("form#productDetailPageBuyProductForm"):
        stock_status = "In Stock"
    else:
        stock_status = stock_text
    warnings = " ".join(text(node) for node in soup.select(".alert, [class*='warning'], [class*='disclaimer']"))
    return {
        "title": title, "link": card["url"], "site_category": normalize_site_category(category),
        "tag": card["tag"], "brand": brand, "sku": sku, "regular_price": regular_price,
        "sale_price": sale_price, "flavor_text": " ".join(flavors), "description": description,
        "package_contents": "", "features": " ".join(devices), "ingredients": "", "warnings": warnings,
        "eliquid_contents": liquid, "puffs": puffs, "coil": "", "battery": extract_battery(combined),
        "power_level": "", "nicotine_strength": nicotine, "stock_status": stock_status,
        "reviews": extract_reviews(soup), "review_attributes": {}, "flavor_list": option_values,
        "nicotine_strengths": [], "image_urls": image_candidates(soup), "html": html,
        "plain_text": soup.get_text(" ", strip=True),
    }


def main():
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/121 Safari/537.36"})
    cache, last_request, processed = {}, 0, 0
    try:
        categories, last_request = discover_categories(session, cache, last_request)
        for category in categories:
            seen = set()
            for page in range(1, MAX_PAGES + 1):
                listing_url = page_url(urljoin(BASE, category), page)
                try:
                    html, last_request = fetch(session, listing_url, cache, last_request)
                except Exception as error:
                    print(f"SKIP listing {listing_url}: {error}")
                    break
                soup = BeautifulSoup(html, "lxml")
                cards = [parse_card(node) for node in soup.select(".card.product-box[data-product-information]")]
                cards = [card for card in cards if card and card["tag"] not in seen]
                print(f"{SITE} {listing_url}: {len(cards)} new cards")
                if not cards:
                    break
                for card in cards:
                    seen.add(card["tag"])
                    if MAX_PRODUCTS and processed >= MAX_PRODUCTS:
                        return
                    try:
                        detail_html, last_request = fetch(session, card["url"], cache, last_request)
                        data = parse_product(detail_html, card, category)
                        product_id = get_product_id(SITE, card["tag"])
                        print(f"PRODUCT {card['title']} [{card['tag']}] {'EXISTS' if product_id else 'NEW'}")
                        if product_id:
                            sync_ecig_product_history(product_id, data)
                            insert_ecig_price(product_id, data["regular_price"], data["sale_price"])
                            if data["reviews"]:
                                insert_reviews(data["reviews"], product_id)
                            if not product_has_images(product_id):
                                images = download_image_batch(data.pop("image_urls"), card["tag"], f"data_from_sites_v2/{SITE}_images", referer=card["url"])
                                insert_product_images(product_id, images)
                        else:
                            data["images"] = download_image_batch(data.pop("image_urls"), card["tag"], f"data_from_sites_v2/{SITE}_images", referer=card["url"])
                            map_product_data(SITE, data)
                        processed += 1
                    except Exception as error:
                        print(f"SKIP product {card['url']}: {error}")
    except Exception as error:
        print(f"VaporFi scraper stopped: {error}")


if __name__ == "__main__":
    main()
