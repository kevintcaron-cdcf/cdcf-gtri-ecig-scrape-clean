"""Mi-Pod scraper for the BigCommerce Stencil storefront."""

import os
import json
import re
import sys
import time
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup, element

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from db.db_azure import (  # noqa: E402
    MIPOD,
    get_product_id,
    insert_ecig_price,
    insert_reviews,
    map_product_data,
    update_ecig_product_metadata,
    sync_ecig_product_history,
)
from ecig_parsing import (  # noqa: E402
    download_image_batch,
    extract_battery,
    find_features,
    normalize_site_category,
    prioritize_links,
    extract_reviews,
)


BASE = "https://mipod.com"
SITE = MIPOD
REQUEST_TIMEOUT = 45
MAX_PAGES = 100
REQUEST_DELAY = 2.0

# Used only if homepage discovery is unavailable. The homepage is the source
# of truth because Mi-Pod can add or remove collections without notice.
FALLBACK_LINKS = [
    "/collections/vape-kits/",
    "/collections/vape-pods/",
    "/collections/vape-juice/",
    "/collections/nicotine-pouches/",
]


def request_url(url):
    parts = urlsplit(urljoin(BASE, url))
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), parts.query, ""))


def canonical_url(url):
    parts = urlsplit(request_url(url))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def text(node):
    return node.get_text(" ", strip=True) if node else ""


def price_value(value):
    match = re.search(r"\d+(?:,\d{3})*(?:\.\d{2})?", value or "")
    return match.group(0).replace(",", "") if match else None


def bc_product_attributes(soup):
    script = soup.select_one('script[type="text/javascript"]')
    if not script or "BCData" not in script.get_text():
        return {}
    match = re.search(r"var\s+BCData\s*=\s*(\{.*?\});", script.get_text(), re.S)
    if not match:
        return {}
    try:
        return json.loads(match.group(1)).get("product_attributes", {})
    except (json.JSONDecodeError, TypeError):
        return {}


def product_identifier(soup, card):
    attributes = bc_product_attributes(soup)
    sku = attributes.get("sku")
    unique_id = card.get("entity_id") or attributes.get("id")
    if not unique_id:
        product_json = soup.select_one('script[type="application/ld+json"]')
        if product_json:
            try:
                unique_id = json.loads(product_json.string or "{}").get("sku")
            except (json.JSONDecodeError, TypeError):
                pass
    return sku, str(unique_id) if unique_id else None


def stock_status(soup):
    attributes = bc_product_attributes(soup)
    if attributes.get("instock") is True:
        return "In Stock"
    availability = text(soup.select_one('meta[property="og:availability"]')).lower()
    if availability in {"instock", "in stock"}:
        return "In Stock"
    if attributes.get("instock") is False or availability in {"oos", "outofstock"}:
        return "Out of Stock"
    return ""


class Fetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.8",
            }
        )
        self.found = {}
        self.last_request = 0.0

    def fetch(self, url):
        url = request_url(url)
        if url in self.found:
            return self.found[url]
        elapsed = time.time() - self.last_request
        if elapsed < REQUEST_DELAY:
            time.sleep(REQUEST_DELAY - elapsed)
        response = self.session.get(url, timeout=REQUEST_TIMEOUT)
        self.last_request = time.time()
        response.raise_for_status()
        if len(response.text) < 500:
            raise RuntimeError(f"Unexpectedly short Mi-Pod response: {url}")
        self.found[url] = response.text
        return response.text


def parse_html(html, selector):
    """Parse a saved page in isolation for quick selector validation."""
    return BeautifulSoup(html, "lxml").select(selector)


def discover_categories(fetcher):
    soup = BeautifulSoup(fetcher.fetch(BASE), "lxml")
    categories = []
    seen = set()
    for link in soup.select("a[href]"):
        path = urlsplit(urljoin(BASE, link["href"])).path.rstrip("/")
        if not path.startswith("/collections/") or path in seen:
            continue
        slug = path.rsplit("/", 1)[-1]
        if slug in {"", "shop-by-type", "shop-by-brand", "shop-by-model"}:
            continue
        seen.add(path)
        categories.append(path)
    if categories:
        print(f"Discovered {len(categories)} Mi-Pod collections")
        return prioritize_links(categories)
    print("No Mi-Pod collections discovered; using fallback links")
    return prioritize_links(FALLBACK_LINKS)


def parse_card(card):
    link = card.select_one('a[href*="/products/"]')
    title = card.select_one(".card-title")
    if not link or not link.get("href") or not title:
        return None
    url = canonical_url(link["href"])
    image = card.select_one("img")
    return {
        "url": url,
        "tag": urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1],
        "entity_id": card.get("data-entity-id"),
        "title": text(title),
        "brand": text(card.select_one('[data-test-info-type="brandName"]')) or None,
        "regular_price": price_value(card.get("data-product-price", "")),
        "sale_price": None,
        "image": (image.get("data-srcset") or image.get("src")) if image else None,
    }


def listing_pages(fetcher, category):
    for page in range(1, MAX_PAGES + 1):
        url = request_url(category)
        if page > 1:
            url = f"{url}?page={page}"
        soup = BeautifulSoup(fetcher.fetch(url), "lxml")
        cards = soup.select("ul.productGrid article.card")
        if not cards:
            return
        yield url, cards
        next_link = soup.select_one('link[rel="next"]')
        if not next_link:
            return


def image_urls(soup):
    seen = set()
    images = []
    # Restrict discovery to BigCommerce's product gallery. The page also
    # contains a nicotine-warning image, site logo, and other content images.
    gallery = soup.select_one(".productView-images")
    if not gallery:
        return images
    for node in gallery.select("[data-image-gallery-zoom-image-url], img"):
        url = node.get("data-image-gallery-zoom-image-url") or node.get("src")
        if not url:
            parent = node.find_parent("a")
            url = parent.get("href") if parent else None
        url = urljoin(BASE, url or "")
        lowered_url = url.lower()
        if (
            url
            and url not in seen
            and not url.startswith("data:")
            and "logo" not in lowered_url
            and "warning" not in lowered_url
            and "caution" not in lowered_url
        ):
            seen.add(url)
            images.append({"url": url, "alt": node.get("alt", "")})
    return images


def parse_product(card, html, site_category):
    soup = BeautifulSoup(html, "lxml")
    title = text(soup.select_one("h1.productView-title")) or card["title"]
    brand = text(soup.select_one("h2.productView-brand")) or card["brand"]
    price = price_value(text(soup.select_one("[data-product-price-with-tax]")))
    if not price:
        meta_price = soup.select_one('meta[property="product:price:amount"]')
        price = price_value(meta_price.get("content", "") if meta_price else "")
    description = text(soup.select_one(".productView-description"))
    plain_text = soup.get_text(" ", strip=True)
    combined = "\n".join(value for value in (description, plain_text) if value)
    _, puffs, nicotine, liquid, _, _ = find_features(combined)

    all_image_urls = image_urls(soup)
    records = download_image_batch(all_image_urls, card["tag"], f"data_from_sites_v2/{SITE}_images")
    print(f'Downloaded {len(records)}/{len(all_image_urls)} images for {card["tag"]}')

    sku, unique_id = product_identifier(soup, card)
    return {
        "title": title,
        "link": card["url"],
        "site_category": site_category,
        "tag": card["tag"],
        "sku": sku,
        "unique_id": unique_id,
        "brand": brand,
        "html": html,
        "plain_text": plain_text,
        "regular_price": price or card["regular_price"],
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
        "stock_status": stock_status(soup),
        "reviews": extract_reviews(soup),
        "review_attributes": {},
        "flavor_list": [],
        "nicotine_strengths": [],
        "images": records,
    }


def main():
    fetcher = Fetcher()
    seen_tags = set()
    stats = {"categories": 0, "cards": 0, "new": 0, "existing": 0, "errors": 0}
    try:
        for category in discover_categories(fetcher):
            stats["categories"] += 1
            site_category = normalize_site_category(category)
            try:
                for page_url, cards in listing_pages(fetcher, category):
                    print(f"LISTING {page_url}: {len(cards)} cards")
                    for card_node in cards:
                        if not isinstance(card_node, element.Tag):
                            continue
                        stats["cards"] += 1
                        card = parse_card(card_node)
                        if not card or card["tag"] in seen_tags:
                            continue
                        seen_tags.add(card["tag"])
                        product_id = get_product_id(SITE, card["tag"])
                        if product_id:
                            print(f"PRODUCT {card['title']} [{card['tag']}] EXISTS")
                            stats["existing"] += 1
                            insert_ecig_price(product_id, card["regular_price"], card["sale_price"])
                            detail = parse_product(card, fetcher.fetch(card["url"]), site_category)
                            sync_ecig_product_history(product_id, detail)
                            print(f"REVIEWS {card['tag']}: {len(detail['reviews'])} found" if detail["reviews"] else f"REVIEWS {card['tag']}: none found")
                            if detail["reviews"]:
                                insert_reviews(detail["reviews"], product_id)
                            update_ecig_product_metadata(
                                product_id, detail["sku"] or detail["unique_id"], detail["stock_status"]
                            )
                            continue
                        print(f"PRODUCT {card['title']} [{card['tag']}] NEW")
                        data = parse_product(card, fetcher.fetch(card["url"]), site_category)
                        map_product_data(SITE, data)
                        stats["new"] += 1
            except Exception as error:
                stats["errors"] += 1
                print(f"Mi-Pod category failed {category}: {error}")
    finally:
        print(f"Mi-Pod summary: {stats}")


if __name__ == "__main__":
    main()
