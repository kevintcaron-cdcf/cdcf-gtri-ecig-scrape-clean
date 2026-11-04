"""Conservative GoPuff scraper.

GoPuff is not included in run_scrape.sh because its markup and access behavior
need to be monitored separately. This script uses a slow, sequential browser
session, a success-only disk cache, bounded retries, and a circuit breaker.
Firefox is visible by default so a human can complete an access challenge;
set GOPUFF_HEADLESS=1 for headless use.
"""

import hashlib
import json
import os
import random
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup, element
from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.support.ui import WebDriverWait

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from db.db_azure import (  # noqa: E402
    GOPUFF,
    get_product_id,
    insert_ecig_price,
    map_product_data,
)
from ecig_parsing import (  # noqa: E402
    download_image,
    extract_battery,
    find_features,
    normalize_site_category,
)


BASE = "https://gopuff.com"
SITE = GOPUFF
LINKS = [
    "/c/tobacco-vapes/txQdWBDe",
    "/c/tobacco-vapes-disposable-vapes/tx5RSEow",
    "/c/tobacco-vapes-cigars-cigarillos/txNBPLxi",
    "/c/tobacco-vapes-smoking-accessories/tx67Z6QK",
    "/c/nicotine-caffeine-pouches/txSqled8",
    "/c/tobacco-vapes-cbd-drinks/tx6SQrFM",
    "/c/tobacco-vapes-cbd-drinks-thc-drinks/txpwzWf7",
    "/c/tobacco-vapes-cbd-drinks-hemp-thc-edibles/txRwdk4t",
    "/c/tobacco-vapes-reusable-vapes-juices/txYjMPOL",
    "/c/tobacco-vapes-cigarettes/txZwi876",
    "/c/tobacco-vapes-rolling-papers/txaLSRsv",
    "/c/tobacco-vapes-hookahs/tx4WpBKu",
    "/c/tobacco-vapes-smokeless-tobacco/tx1PGOGr",
]

# GoPuff changes the opaque IDs in category URLs periodically. These are only
# fallback seeds; the scraper first discovers current links from the site.
CATEGORY_PATH_RE = re.compile(r"^/c/(?:tobacco|nicotine)[^?#]*", re.I)

CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache", "gopuff")
CACHE_TTL_SECONDS = 24 * 60 * 60
REQUEST_TIMEOUT = 45
MAX_RETRIES = 2
MAX_PAGES = 50
MAX_BLOCKS = 3
MIN_REQUEST_DELAY = 3.0
MAX_REQUEST_DELAY = 8.0
CHALLENGE_WAIT_SECONDS = 300

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)


def canonical_url(url):
    """Remove query/fragment noise so cache and database identity are stable."""
    absolute = urljoin(BASE, url or "")
    parts = urlsplit(absolute)
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def request_url(url):
    """Canonicalize a request while retaining pagination query parameters."""
    absolute = urljoin(BASE, url or "")
    parts = urlsplit(absolute)
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), parts.query, ""))


def cache_paths(url):
    key = hashlib.sha256(request_url(url).encode("utf-8")).hexdigest()
    return os.path.join(CACHE_DIR, f"{key}.html"), os.path.join(CACHE_DIR, f"{key}.json")


def load_cached_page(url, allow_stale=False):
    html_path, metadata_path = cache_paths(url)
    if not os.path.exists(html_path) or not os.path.exists(metadata_path):
        return None
    try:
        with open(metadata_path, "r", encoding="utf-8") as handle:
            metadata = json.load(handle)
        age = time.time() - float(metadata["saved_at"])
        if not allow_stale and age > CACHE_TTL_SECONDS:
            return None
        with open(html_path, "r", encoding="utf-8") as handle:
            html = handle.read()
        if not html or metadata.get("blocked") or metadata.get("status_code", 200) >= 400:
            return None
        return html
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_cached_page(url, html, status_code=200):
    """Write only a page that looks like a successful HTML document."""
    if not html or len(html) < 500 or status_code >= 400:
        return
    os.makedirs(CACHE_DIR, exist_ok=True)
    html_path, metadata_path = cache_paths(url)
    metadata = {
        "url": canonical_url(url),
        "saved_at": time.time(),
        "status_code": status_code,
        "content_length": len(html),
        "blocked": False,
    }
    try:
        with open(html_path, "w", encoding="utf-8") as handle:
            handle.write(html)
        with open(metadata_path, "w", encoding="utf-8") as handle:
            json.dump(metadata, handle)
    except OSError as error:
        print(f"Cache write failed for {url}: {error}")


def retry_after_seconds(value):
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            return max(0.0, (date - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def backoff(attempt, retry_after=None):
    delay = retry_after if retry_after is not None else min(300, 5 * (2**attempt))
    delay += random.uniform(0, min(5, max(1, delay * 0.25)))
    print(f"Waiting {delay:.1f}s before retry")
    time.sleep(delay)


def block_reason(status_code, html):
    if not html:
        return "empty response"
    if status_code in (403, 429):
        return f"HTTP {status_code}"

    soup = BeautifulSoup(html, "lxml")
    title = text(soup.find("title")).lower()
    body = text(soup.body).lower() if soup.body else text(soup).lower()
    challenge_selectors = (
        "#challenge-form",
        "#cf-chl-widget",
        "[name='cf-turnstile-response']",
        "iframe[src*='captcha']",
        "iframe[src*='challenge']",
    )
    if any(soup.select_one(selector) for selector in challenge_selectors):
        return "challenge form"
    if any(
        marker in title or marker in body[:5000]
        for marker in (
            "verify you are human",
            "access denied",
            "temporarily blocked",
            "too many requests",
            "just a moment",
        )
    ):
        return "challenge or block page"
    if html and len(html) < 500:
        return "unexpectedly short response"
    return None


class CircuitBreaker:
    def __init__(self):
        self.blocks = 0

    def record(self, reason):
        self.blocks += 1
        print(f"GoPuff block {self.blocks}/{MAX_BLOCKS}: {reason}")
        if self.blocks >= MAX_BLOCKS:
            raise RuntimeError("GoPuff circuit breaker opened after repeated blocks")


class GoPuffFetcher:
    def __init__(self):
        self.driver = None
        self.last_request = 0.0
        self.breaker = CircuitBreaker()
        self.headless = os.environ.get("GOPUFF_HEADLESS", "0").lower() in {
            "1", "true", "yes"
        }

    def start(self):
        options = Options()
        if self.headless:
            options.add_argument("--headless")
        options.page_load_strategy = "eager"
        options.set_preference("general.useragent.override", USER_AGENT)
        self.driver = webdriver.Firefox(options=options)
        self.driver.set_page_load_timeout(REQUEST_TIMEOUT)

    def wait_for_challenge(self, url):
        """Give a headed browser time for a human to complete GoPuff's check."""
        if self.headless or not self.driver:
            return None
        # The terminal bell makes the challenge actionable when the browser is
        # behind another window or the scraper is running in the background.
        sys.stdout.write("\a")
        sys.stdout.flush()
        print(
            f"GoPuff challenge detected for {url}. Complete it in the visible "
            f"Firefox window; waiting up to {CHALLENGE_WAIT_SECONDS}s."
        )
        deadline = time.monotonic() + CHALLENGE_WAIT_SECONDS
        while time.monotonic() < deadline:
            html = self.driver.page_source or ""
            if not block_reason(200, html):
                print("GoPuff challenge cleared")
                return html
            time.sleep(2)
        return None

    def close(self):
        if self.driver:
            try:
                self.driver.quit()
            except WebDriverException:
                pass
            self.driver = None

    def pace(self):
        elapsed = time.time() - self.last_request
        delay = random.uniform(MIN_REQUEST_DELAY, MAX_REQUEST_DELAY)
        if elapsed < delay:
            time.sleep(delay - elapsed)
        self.last_request = time.time()

    def fetch(self, url, allow_stale_cache=False):
        url = request_url(url)
        cached = load_cached_page(url, allow_stale=allow_stale_cache)
        if cached:
            print(f"CACHE {url}")
            return cached

        headers = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.8"}
        last_reason = None
        for attempt in range(MAX_RETRIES + 1):
            self.pace()
            status_code = 200
            direct_html = ""
            retry_after = None
            direct_reason = None
            browser_reason = None
            try:
                response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
                status_code = response.status_code
                direct_html = response.text
                retry_after = retry_after_seconds(response.headers.get("Retry-After"))
                direct_reason = block_reason(status_code, direct_html)
                if not direct_reason:
                    # Requests may contain enough server-rendered markup to parse.
                    if "ProductTile" in direct_html or "/p/" in direct_html:
                        save_cached_page(url, direct_html, status_code)
                        return direct_html
            except requests.RequestException as error:
                print(f"Direct request failed for {url}: {error}")
                direct_reason = "request failure"

            try:
                if not self.driver:
                    self.start()
                self.driver.get(url)
                WebDriverWait(self.driver, REQUEST_TIMEOUT).until(
                    lambda driver: driver.find_elements(By.TAG_NAME, "body")
                )
                time.sleep(random.uniform(2, 4))
                rendered_html = self.driver.page_source or direct_html
                # Selenium has no response status here. Do not carry a failed
                # direct-request status into an otherwise valid browser page.
                browser_reason = block_reason(200, rendered_html)
                if browser_reason:
                    print(
                        f"Browser response blocked for {url}: {browser_reason} "
                        f"({len(rendered_html)} bytes)"
                    )
                    cleared_html = self.wait_for_challenge(url)
                    if cleared_html:
                        save_cached_page(url, cleared_html, 200)
                        return cleared_html
                    last_reason = browser_reason
                elif rendered_html and len(rendered_html) >= 500:
                    save_cached_page(url, rendered_html, 200)
                    return rendered_html
            except (TimeoutException, WebDriverException) as error:
                print(f"Browser fetch failed for {url}: {error}")
                last_reason = "browser fetch failure"

            if direct_reason and not browser_reason:
                last_reason = direct_reason
            if attempt < MAX_RETRIES:
                backoff(attempt, retry_after)

        self.breaker.record(last_reason or "unknown fetch failure")
        raise RuntimeError(f"Unable to fetch GoPuff URL: {url}")


def category_name(path):
    return normalize_site_category(urlsplit(path).path)


def product_tag(url):
    parts = [part for part in urlsplit(canonical_url(url)).path.split("/") if part]
    return parts[-1] if parts else ""


def text(node):
    return node.get_text(" ", strip=True) if node else ""


def unique_image_urls(soup):
    images = []
    seen = set()
    gallery = soup.select_one(".glide__track") or soup
    for image in gallery.find_all("img"):
        alt = image.get("alt", "").strip()
        for attribute in ("data-srcset", "srcset", "src", "data-src"):
            value = image.get(attribute)
            if not value:
                continue
            candidates = value.split(",") if "srcset" in attribute else [value]
            for candidate in candidates:
                image_url = candidate.strip().split(" ")[0]
                image_url = urljoin(BASE, image_url)
                if image_url and image_url not in seen and not image_url.startswith("data:"):
                    seen.add(image_url)
                    images.append({"url": image_url, "alt": alt})
            break
    return images


def extract_price(card):
    sale = text(card.find("span", {"data-testid": "SalePriceOffered"}))
    current = text(card.find("span", {"data-testid": "RetailPriceOffered"}))
    original = text(card.find("span", {"data-testid": "RetailPriceStrikethrough"}))
    if sale:
        return original or current, sale
    return current, None


def extract_brand(title):
    known = ("Geek Bar", "Hyde", "Puff Bar", "Elf Bar", "Lost Mary", "Fume", "Raz", "Air Bar")
    return next((brand for brand in known if title.lower().startswith(brand.lower())), None)


def parse_card(card):
    link_tag = card.find("a", {"data-testid": "ProductLink"})
    if not link_tag:
        link_tag = card.find("a", href=re.compile(r"/p/"))
    if not link_tag or not link_tag.get("href"):
        return None
    url = canonical_url(link_tag["href"])
    title_node = card.find("span", {"data-testid": "ProductTileName"})
    if not title_node:
        title_node = card.find("img")
    if not title_node:
        return None
    title = text(title_node) if title_node.name != "img" else title_node.get("alt", "").strip()
    if not title:
        return None
    regular_price, sale_price = extract_price(card)
    return {
        "url": url,
        "tag": product_tag(url),
        "title": title,
        "brand": extract_brand(title),
        "regular_price": regular_price,
        "sale_price": sale_price,
    }


def parse_product(card_data, html, site_category):
    soup = BeautifulSoup(html, "lxml")
    root = soup.find("div", {"data-testid": "grid-item"}) or soup
    title_node = root.find("h1")
    title = text(title_node) or card_data["title"]
    description_node = (
        root.find("div", {"data-testid": "product-description"})
        or root.find("div", class_=re.compile("product-description", re.I))
        or root.find("section", {"aria-label": re.compile("Product Details", re.I)})
        or root.find("div", id="description")
    )
    description = text(description_node)
    if not description:
        description = text(root)[:4000]

    features = []
    for section in root.select(".specification, .product-specs, dl"):
        value = text(section)
        if value and value not in features:
            features.append(value)
    feature_text = "\n".join(features)
    combined_text = "\n".join(value for value in (description, feature_text) if value)
    _, puffs, nicotine, liquid, _, _ = find_features(combined_text)

    images = unique_image_urls(soup)
    image_records = []
    for number, image in enumerate(images, start=1):
        saved = download_image(
            image["url"],
            card_data["tag"],
            save_dir=f"data_from_sites_v2/{SITE}_images",
            alt=image.get("alt", ""),
            number_append=number,
        )
        if saved:
            image_records.append(saved)
    print(f'Downloaded {len(image_records)}/{len(images)} images for {card_data["tag"]}')

    return {
        "title": title,
        "link": card_data["url"],
        "site_category": site_category,
        "tag": card_data["tag"],
        "brand": card_data["brand"],
        "html": html,
        "plain_text": soup.get_text(" ", strip=True),
        "regular_price": card_data["regular_price"],
        "sale_price": card_data["sale_price"],
        "flavor_text": "",
        "description": description,
        "package_contents": "",
        "features": feature_text,
        "ingredients": "",
        "warnings": "",
        "eliquid_contents": liquid,
        "puffs": puffs,
        "coil": "",
        "battery": extract_battery(combined_text),
        "power_level": "",
        "nicotine_strength": nicotine,
        "stock_status": "",
        "reviews": [],
        "review_attributes": {},
        "flavor_list": [],
        "nicotine_strengths": [],
        "images": image_records,
    }


def listing_pages(fetcher, category):
    """Yield category pages until no new product cards are found."""
    seen_page_signatures = set()
    for page in range(1, MAX_PAGES + 1):
        url = request_url(category)
        if page > 1:
            url = f"{url}?page={page}"
        html = fetcher.fetch(url)
        soup = BeautifulSoup(html, "lxml")
        cards = soup.find_all("div", {"data-testid": "ProductTile"})
        signature = hashlib.sha256("|".join(text(card) for card in cards).encode()).hexdigest()
        if not cards or signature in seen_page_signatures:
            return
        seen_page_signatures.add(signature)
        yield url, cards


def discover_categories(fetcher):
    """Read current category URLs instead of relying on expired opaque IDs."""
    html = fetcher.fetch(BASE)
    soup = BeautifulSoup(html, "lxml")
    discovered = []
    seen = set()
    for link in soup.find_all("a", href=True):
        href = link["href"].strip()
        path = urlsplit(urljoin(BASE, href)).path.rstrip("/")
        if not CATEGORY_PATH_RE.match(path) or path in seen:
            continue
        seen.add(path)
        discovered.append(path)
    if discovered:
        print(f"Discovered {len(discovered)} current GoPuff categories")
        return discovered
    print("No current GoPuff categories discovered; using fallback category URLs")
    return LINKS


def main():
    fetcher = GoPuffFetcher()
    seen_tags = set()
    stats = {"categories": 0, "cards": 0, "new": 0, "existing": 0, "errors": 0}
    try:
        for category in discover_categories(fetcher):
            stats["categories"] += 1
            category_url = canonical_url(category)
            site_category = category_name(category_url)
            print(f"CATEGORY {category_url}")
            try:
                pages = listing_pages(fetcher, category_url)
                for page_url, cards in pages:
                    print(f"LISTING {page_url}: {len(cards)} cards")
                    for card in cards:
                        if not isinstance(card, element.Tag):
                            continue
                        stats["cards"] += 1
                        card_data = parse_card(card)
                        if not card_data or not card_data["tag"] or card_data["tag"] in seen_tags:
                            continue
                        seen_tags.add(card_data["tag"])
                        product_id = get_product_id(SITE, card_data["tag"])
                        if product_id:
                            stats["existing"] += 1
                            insert_ecig_price(product_id, card_data["regular_price"], card_data["sale_price"])
                            continue

                        product_html = fetcher.fetch(card_data["url"])
                        product_data = parse_product(card_data, product_html, site_category)
                        map_product_data(SITE, product_data)
                        stats["new"] += 1
            except RuntimeError as error:
                print(f"STOPPING GoPuff after category failure: {error}")
                break
            except Exception as error:
                stats["errors"] += 1
                print(f"Category failed {category_url}: {error}")
                traceback.print_exc()
    finally:
        fetcher.close()
        print(f"GoPuff summary: {stats}")


if __name__ == "__main__":
    main()
