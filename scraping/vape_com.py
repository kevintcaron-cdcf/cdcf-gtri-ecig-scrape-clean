"""Vape.com scraper pilot for the current Next.js storefront."""

import json
import os
import re
import sys
import time
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from db.db_azure import (  # noqa: E402
    VAPE_DOT_COM,
    get_product_id,
    insert_ecig_price,
    insert_product_images,
    insert_reviews,
    map_product_data,
    product_has_images,
    sync_ecig_product_history,
    update_ecig_product_metadata,
)
from ecig_parsing import (  # noqa: E402
    download_image_batch,
    extract_battery,
    find_features,
    normalize_site_category,
    prioritize_links,
    extract_reviews,
)


BASE = "https://vape.com"
LINKS = ["/"]
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/121 Safari/537.36"}


def product_urls(html):
    soup = BeautifulSoup(html, "lxml")
    urls = []
    seen = set()
    for link in soup.select('a[href*="/products/"], a[href*="/product/"]'):
        url = urljoin(BASE, link.get("href", "")).split("?", 1)[0]
        if url not in seen and url.rstrip("/") != BASE:
            seen.add(url)
            urls.append(url)
    return urls


def category_urls(html):
    soup = BeautifulSoup(html, "lxml")
    urls = []
    seen = set()
    for link in soup.select('a[href]'):
        href = link.get("href", "")
        if "/products/" in href or "/product/" in href or href in {"/", "#"} or href.startswith("#"):
            continue
        url = urljoin(BASE, href).split("?", 1)[0]
        if url.startswith(BASE) and "/collections/" in url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def json_ld_product(soup):
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        values = value if isinstance(value, list) else [value]
        for item in values:
            if isinstance(item, dict) and item.get("@type") == "Product":
                return item
    return {}


def parse_product(url, html, category):
    soup = BeautifulSoup(html, "lxml")
    structured = json_ld_product(soup)
    title = structured.get("name") or (soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else "")
    tag = urlsplit(url).path.rstrip("/").split("/")[-1]
    plain_text = soup.get_text(" ", strip=True)
    description = structured.get("description", "")
    combined = "\n".join((description, plain_text))
    _, puffs, nicotine, liquid, _, _ = find_features(combined)
    image_urls = structured.get("image", [])
    if isinstance(image_urls, str):
        image_urls = [image_urls]
    images = [{"url": urljoin(BASE, image), "alt": title} for image in image_urls if image]
    if not images:
        for image in soup.select('meta[property="og:image"], img'):
            image_url = image.get("content") or image.get("src") or image.get("data-src")
            if image_url and "logo" not in image_url.lower():
                images.append({"url": urljoin(BASE, image_url), "alt": title})
    images = download_image_batch(images, tag, "data_from_sites_v2/VAPE.COM_images")
    offers = structured.get("offers", {})
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    price = offers.get("price") if isinstance(offers, dict) else None
    sku = structured.get("sku") or structured.get("mpn") or tag
    return {
        "title": title, "link": url, "site_category": normalize_site_category(category), "tag": tag,
        "sku": sku, "brand": (structured.get("brand") or {}).get("name") if isinstance(structured.get("brand"), dict) else structured.get("brand"),
        "html": html, "plain_text": plain_text, "regular_price": price, "sale_price": None,
        "flavor_text": "", "description": description, "package_contents": "", "features": "",
        "ingredients": "", "warnings": "", "eliquid_contents": liquid, "puffs": puffs,
        "coil": "", "battery": extract_battery(combined), "power_level": "",
        "nicotine_strength": nicotine, "stock_status": "In Stock" if offers.get("availability", "").endswith("InStock") else "",
        "reviews": extract_reviews(soup), "review_attributes": {}, "flavor_list": [], "nicotine_strengths": [], "images": images,
    }


def main():
    session = requests.Session()
    session.headers.update(HEADERS)
    seen = set()
    options = Options()
    if os.environ.get("HEADLESS", "0").lower() not in {"0", "false", "no"}:
        options.add_argument("--headless")
    driver = webdriver.Firefox(options=options)
    homepage = session.get(BASE, timeout=45)
    homepage.raise_for_status()
    categories = category_urls(homepage.text)
    # The homepage links are present in the HTML, but category content may be
    # rendered through route-specific Next.js data. Keep the known current
    # storefront routes as a fallback when a page yields no product links.
    categories.extend(urljoin(BASE, path) for path in (
        "/collections/new-arrivals",
        "/collections/disposable-e-cigs",
        "/collections/e-liquids",
        "/collections/starter-kits",
        "/collections/devices",
        "/collections/tanks",
        "/collections/accessories",
        "/collections/alternatives",
        "/collections/clearance",
    ) if urljoin(BASE, path) not in categories)
    try:
        for category in prioritize_links(categories):
            driver.get(category)
            WebDriverWait(driver, 30).until(
                lambda current: current.find_elements(By.TAG_NAME, "body")
            )
            time.sleep(3)
            rendered_html = driver.page_source
            urls = product_urls(rendered_html)
            print(f"VAPE.COM {category}: {len(urls)} product links")
            for url in urls:
                if url in seen:
                    continue
                seen.add(url)
                detail = session.get(url, timeout=45)
                if detail.status_code == 404:
                    print(f"SKIP 404 {url}")
                    continue
                detail.raise_for_status()
                data = parse_product(url, detail.text, category)
                product_id = get_product_id(VAPE_DOT_COM, data["tag"])
                print(f"PRODUCT {data['title']} [{data['tag']}] {'EXISTS' if product_id else 'NEW'}")
                print(f"REVIEWS {data['tag']}: {len(data['reviews'])} found" if data["reviews"] else f"REVIEWS {data['tag']}: none found")
                if product_id:
                    insert_ecig_price(product_id, data["regular_price"], data["sale_price"])
                    sync_ecig_product_history(product_id, data)
                    if data["reviews"]:
                        insert_reviews(data["reviews"], product_id)
                    if not product_has_images(product_id):
                        insert_product_images(product_id, data["images"])
                    update_ecig_product_metadata(product_id, data["sku"], data["stock_status"])
                else:
                    map_product_data(VAPE_DOT_COM, data)
                time.sleep(2)
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
