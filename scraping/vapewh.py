
import requests
import re
from bs4 import BeautifulSoup, element
import time
import pandas as pd
import random
import csv
import sys
import os
import traceback

from selenium.common.exceptions import InvalidSessionIdException, NoSuchElementException, TimeoutException

import json
from datetime import datetime, timedelta

from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities




sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from db.db_azure import *
from ecig_parsing import *


BASE = 'https://vapewh.com' 
company = VAPE_WH


links = [
    # Current WordPress/WooCommerce category and brand paths from the menu.
    "/product-category/deals/",
    "/product-category/all-disposable-e-cigs/",
    "/product-category/3-nicotine-disposable-vapes/",
    "/product-category/newest-arrivals/",
    "/product-category/smart-vapes/",
    "/product-category/liquid-visible/",
    "/product-category/all-lower-nicotine-vapes/",
    "/brand/geek-bar/",
    "/brand/lost-mary/",
    "/brand/raz-vapes/",
    "/brand/realio-vapes/",
    "/brand/off-stamp/",
    "/brand/ijoy/",
    "/brand/dinner-lady/",
    "/brand/oxbar/",
    "/brand/juul/",
    "/product-category/e-liquid/",
    "/product-category/sub-ohm/",
    "/product-category/all-hardware/",
    "/product-category/mods-kits/",
    "/product-category/tanks-coils/",
    "/product-category/nicotine-salt/",
    "/product-category/replacement-pods/",
]

print('TOTAL LINKS', len(links))
found = dict()


def _absolutize(url) -> str:
    if not url:
        return ""
    return ("https:" + url) if url.startswith("//") else url

def parse_review_card(card):
    """Extract review data from a single review 'card' BeautifulSoup element."""
    # --- Author + verified ---
    author = None
    title_div = card.select_one('div.block.title')
    if title_div:
        for child in title_div.children:
            if getattr(child, "name", None) is None:
                txt = str(child).strip()
                if txt:
                    author = txt
                    break
    verified = title_div.select_one(".verified-badge-and-text") is not None if title_div else False

    # --- Date ---
    date_text = None
    date_iso = None
    date_div = card.select_one('[data-testid$="-date"]')
    if date_div:
        date_text = date_div.get_text(strip=True)
        # Try common mm/dd/yyyy; fallback to regex
        try:
            date_iso = datetime.strptime(date_text, "%m/%d/%Y").date().isoformat()
        except Exception:
            m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", date_text or "")
            if m:
                mm, dd, yyyy = map(int, m.groups())
                date_iso = datetime(yyyy, mm, dd).date().isoformat()

    # --- Stars ---
    stars = None
    stars_block = card.select_one('[data-testid$="-stars"]')
    if stars_block:
        full_icons = stars_block.select('svg[data-lx-fill="full"]')
        count = len(full_icons)
        if count > 0:
            stars = count
        else:
            aria = stars_block.get("aria-label") or ""
            m = re.search(r"(\d+)\s*/\s*5", aria)
            if m:
                stars = int(m.group(1))

    # --- Review text ---
    review_text = None
    text_div = card.select_one('.pre-wrap.main-text:not(.reply-text)')
    if text_div:
        review_text = text_div.get_text(" ", strip=True)

    # --- Item/variant (metadata) ---
    item_type = None
    meta_value = card.select_one(".metadata .value")
    if meta_value:
        item_type = meta_value.get_text(" ", strip=True)

    # --- Image URL (if any) ---
    image_url = None
    media_img = card.select_one('[data-testid$="-media"] img')
    if media_img and media_img.get("src"):
        image_url = _absolutize(media_img["src"])

    # --- Merchant reply (if any) ---
    reply_from = None
    reply_text = None
    reply_title = card.select_one('.item-reply-title')
    if reply_title:
        strong = reply_title.select_one("strong")
        if strong:
            reply_from = strong.get_text(strip=True)
    reply_body = card.select_one('.reply-text')
    if reply_body:
        reply_text = reply_body.get_text(" ", strip=True)

    # --- Review ID (from data-testid like 'review-<id>-...') ---
    review_id = None
    any_dt = card.select_one('[data-testid^="review-"]')
    if any_dt:
        m = re.search(r"review-([^-]+)", any_dt.get("data-testid", ""))
        if m:
            review_id = m.group(1)

    return {
        "review_id": review_id,
        "author": author,
        "verified_buyer": verified,
        "date": date_iso,
        "rating": stars,
        "review_text": review_text,
        "variant": item_type,
        "image_url": image_url,
        "reply_from": reply_from,
        "reply_text": reply_text,
    }

def extract_section_text(soup, keywords):
    if not soup:
        return ""
    for det in soup.find_all(['detail', 'details']):
        section_header = det.find('summary')
        if section_header:
            header_text = section_header.get_text(" ", strip=True).lower()
            if any(kw in header_text for kw in keywords):
                content = det.find('div', class_='rte carousel-content')
                if content:
                    content = content.get_text(" ", strip=True)
                else:
                    content = det.get_text(" ", strip=True)
                return content
    return ""

def extract_options_generic(soup, keywords):
    """
    Return a flat list of option values for any label/heading/select whose text matches keywords.
    keywords: iterable of strings to search for (case-insensitive, partial match)
    """
    def _norm(s):
        return re.sub(r"\s+", " ", s or "").strip()

    matches = []

    # Case-insensitive set of keywords
    kw_lower = [k.lower() for k in keywords]

    def _matches_label(txt):
        t = (txt or "").strip().lower()
        return any(k in t for k in kw_lower)

    # Find labels and headings with matching text, grab options
    for tag in soup.find_all(["label", "strong", "span", "h1", "h2", "h3", "h4", "h5", "h6"], role=True) + \
               soup.find_all(["label", "strong", "span", "h1", "h2", "h3", "h4", "h5", "h6"]):
        if _matches_label(tag.get_text(" ", strip=True)):
            sel = None
            if tag.has_attr("for"):
                sel = soup.select_one(f'select#{tag["for"]}')
            sel = sel or tag.find_next("select")
            if sel:
                for opt in sel.select("option"):
                    val = _norm(opt.get_text())
                    if val:
                        matches.append(val)

    # Fallback: any selects whose name attribute matches keywords
    for sel in soup.select("select"):
        name_attr = sel.get("name", "").lower()
        if any(k in name_attr for k in kw_lower):
            for opt in sel.select("option"):
                val = _norm(opt.get_text())
                if val:
                    matches.append(val)

    # Hidden variant-wrapper divs with data-optionX attributes
    for vdiv in soup.select("[id^='variant-']"):
        for k in ("data-option1", "data-option2", "data-option3"):
            if vdiv.has_attr(k) and _matches_label(k):  # Only if attribute name matches keyword
                val = _norm(vdiv.get(k))
                if val:
                    matches.append(val)

    # Deduplicate while preserving order
    seen = set()
    return [m for m in matches if not (m in seen or seen.add(m))]

def get_reviews(psoup):
    reviews = []
    reviews_section = psoup.find('iframe', id='looxReviewsFrame')
    if reviews_section:
        iframe_src = reviews_section.get('src')
        if iframe_src:
            print('REVIEWS IFRAME SRC', iframe_src)
            reviews_html = get_html(iframe_src, load_more=True, clicked=True, closed=True)
            reviews_soup = BeautifulSoup(reviews_html, features="lxml") 
            review_items = reviews_soup.find_all('div', class_='grid-item-wrap has-img')
            for ri in review_items:
                #print('REVIEW ITEM', ri )
                ri_info = parse_review_card(ri)
                if ri_info:
                    reviews.append(ri_info)
    return reviews


def download_product_images(soup, tag, site_dir, referer=None, driver=None):
    candidates = []
    seen = set()
    cookies = {cookie['name']: cookie['value'] for cookie in driver.get_cookies()} if driver else None
    for image in soup.select('.productView-images img, .woocommerce-product-gallery img, img.wp-post-image'):
        url = image.get('data-large_image') or image.get('data-src') or image.get('src')
        if not url or url in seen or url.startswith('data:'):
            continue
        seen.add(url)
        candidates.append({'url': url, 'alt': image.get('alt', '')})
    return download_image_batch(
        candidates, tag, site_dir, referer=referer or BASE, cookies=cookies
    )


def create_driver():
    options = Options()
    if os.environ.get("HEADLESS", "1").lower() not in {"0", "false", "no"}:
        options.add_argument('--headless')
    return webdriver.Firefox(options=options)

def get_html(url, clicked=False, closed=False, elements=True, load_more=False, driver=None):

    owns_driver = driver is None
    try:
        if owns_driver:
            driver = create_driver()
        driver.get(url)
        if not driver.find_elements(By.TAG_NAME, "body"):
            raise RuntimeError("Vape WH returned no document body")
        last_n = 0
        hrefs = set()
        button_id = 'ac-ag-yes-button'

        html = driver.page_source
        time.sleep(1)
        same_count = 0

        # wait = WebDriverWait(driver, 10) 
        # wait.until(EC.visibility_of_element_located((By.CLASS_NAME, "modal-content")))

        if not clicked:
            # The age gate is optional. Its absence is normal after the site
            # cookie is set, and must not turn a valid page into empty HTML.
            for locator in (
                (By.ID, "ac-ag-yes-button"),
                (By.CLASS_NAME, "age-yes"),
                (By.XPATH, "//button[normalize-space()='Yes']"),
                (By.XPATH, "//button[contains(translate(., 'YESIAM', 'yesiam'), 'yes')]") ,
            ):
                try:
                    button = WebDriverWait(driver, 2).until(
                        EC.element_to_be_clickable(locator)
                    )
                    button.click()
                    time.sleep(1)
                    break
                except (TimeoutException, NoSuchElementException):
                    continue

        if not closed:
            wait = WebDriverWait(driver, 10)  # wait up to 10 seconds

            try:
                # Wait for the button to be visible and clickable
                button = wait.until(
                    EC.element_to_be_clickable(
                        (By.XPATH, "//button[normalize-space(text())=\"No thanks, I'll pay full price\"]")
                    )
                )
                button.click()
                #print("Button clicked.")
            except TimeoutException:
                # The promotion is optional; absence means there is nothing
                # to dismiss and should not look like a scraper failure.
                pass

        # Set a delay for dynamic content loading
        SCROLL_PAUSE_TIME = 1  # Shorter pause for smoother scroll

        # Scroll incrementally by a small step (e.g., 500 pixels)
        scroll_increment = 750

        # Get the initial scroll height
        last_height = driver.execute_script("return document.body.scrollHeight")
        first_height = last_height
        # print(last_height)

        while True:
            # Scroll down by the increment
            driver.execute_script(f"window.scrollBy(0, {scroll_increment});")

            # Wait for the page to load new content
            time.sleep(SCROLL_PAUSE_TIME)

            # Calculate the new scroll height
            new_height = driver.execute_script("return document.body.scrollHeight")

            # Check if new elements have appeared on the screen
            # You can check specific elements like this:
            # elements = driver.find_elements(By.CLASS_NAME, "your-element-class")

            # If the scroll height has not changed, break the loop
            #print(same_count, new_height, last_height)
            if new_height == last_height :
                same_count += 1
                if same_count >= 3:
                    break
            else:
                same_count = 0

            # Update the last height
            last_height = new_height

        
        # 
        if load_more:
            wait = WebDriverWait(driver, 10)
            while True:
                try:
                    # Wait until the button is visible and clickable
                    button = wait.until(EC.element_to_be_clickable((By.ID, "loadMore")))
                    button.click()

                except TimeoutException:
                    # No more button found — exit the loop
                    break
        html = driver.page_source

    except Exception as ex:
        # A browser session can disappear during a long run.  Do not query
        # page_source again here: doing so raises InvalidSessionIdException
        # and hides the original failure from the caller.
        print(ex)
        if isinstance(ex, InvalidSessionIdException):
            raise
        html = ''
        if driver:
            try:
                html = driver.page_source or ''
            except Exception:
                html = ''
    finally:
        if driver and owns_driver:
            try:
                html = driver.page_source or html
            except Exception:
                pass
            driver.quit()
    time.sleep(3)

    return html

def main():
    from collections import Counter

    product_list = list()
    all_headers = list()
    header_counter = Counter(all_headers)
    header_samples = dict()
    
    has_header = False
    
    driver = create_driver()
    try:
        homepage = requests.get(BASE, timeout=45)
        discovered = discover_catalog_links(
            homepage.text,
            BASE,
            prefixes=("/product-category/", "/brand/"),
            exclude=("/cart", "/my-account", "/search", "/blog", "/about", "/contact"),
        )
        scrape_links = list(dict.fromkeys(links + discovered))
        print(f"Discovered {len(discovered)} Vape WH catalog links; using {len(scrape_links)} total")
        section_links = list(prioritize_links(scrape_links))
        if not section_links:
            print("No Vape WH catalog links available")
            return
        section_index = 0
        top_level_link = section_links[section_index]
        page = 1
        site_section = normalize_site_category(top_level_link)
        seen_page_signatures = set()

        while section_index < len(section_links):
            url = f'{BASE}{top_level_link}?page={page}'
            print(url)

            if url in found:
                reqtxt = found[url]
            else:
                try:
                    reqtxt = get_html(url, driver=driver)
                except InvalidSessionIdException:
                    print(f"WebDriver session failed while loading {url}; restarting browser once")
                    try:
                        driver.quit()
                    except Exception:
                        pass
                    driver = create_driver()
                    reqtxt = get_html(url, driver=driver)
                found[url] = reqtxt
            #reqtxt = get_html(url)
            soup = BeautifulSoup(reqtxt, features="lxml")
            products = soup.select(
                'product-card, .product-card, .pcard-plp, '
                '[data-product-card], [data-product-id], '
                'li.product, .woocommerce ul.products li.product, '
                '.products.columns-4 > li, .products.columns-3 > li, '
                '.category-section-grid .products-section-card'
            )
            print(url, len(products))
            if not products and len(reqtxt) < 1000:
                print(f"Vape WH returned an empty/blocked page ({len(reqtxt)} bytes): {url}")
            
            if len(products) == 0:
                section_index += 1
                if section_index >= len(section_links):
                    break
                top_level_link = section_links[section_index]
                site_section = normalize_site_category(top_level_link)
                page = 1
                seen_page_signatures = set()
                continue

            page_signature = tuple(
                sorted(
                    (product.select_one("a[href]") or {}).get("href", "")
                    for product in products
                )
            )
            if page_signature in seen_page_signatures:
                print(f"Repeated product page detected for {top_level_link}; moving to next section")
                section_index += 1
                if section_index >= len(section_links):
                    break
                top_level_link = section_links[section_index]
                site_section = normalize_site_category(top_level_link)
                page = 1
                seen_page_signatures = set()
                continue
            seen_page_signatures.add(page_signature)

            if page > 100:
                print('PAGE LIMIT REACHED, BREAKING SECTION')
                section_index += 1
                if section_index >= len(section_links):
                    break
                top_level_link = section_links[section_index]
                site_section = normalize_site_category(top_level_link)
                page = 1
                seen_page_signatures = set()
                continue
            page += 1

            for product in products:
                if not isinstance(product, element.Tag):
                    continue

                # Title
                title_node = product.select_one(
                    ".product-card__title, .product-title, "
                    ".woocommerce-loop-product__title, h2.woocommerce-loop-product__title, "
                    ".products-section-card-description"
                )
                if not title_node:
                    continue
                title = title_node.get_text(strip=True)

                # Product URL
                product_link = product.select_one(
                    ".product-card__title[href], .product-title[href], "
                    "a[href*='/products/'], a.woocommerce-LoopProduct-link, "
                    "a[href*='/product/'], .products-section-card-image[href], "
                    ".products-section-card-button[href], [data-product-url]"
                )
                if product_link:
                    product_url_path = product_link.get('href') or product_link.get('data-product-url')
                else:
                    continue
                full_link = requests.compat.urljoin(BASE, product_url_path)
                tag = product_url_path.rstrip('/').split('/')[-1].split('?')[0]

                print(full_link)

                if full_link in found:
                    product_html = found[full_link]
                else:
                    try:
                        product_html = get_html(full_link, driver=driver)
                    except InvalidSessionIdException:
                        print(f"WebDriver session failed while loading {full_link}; restarting browser once")
                        try:
                            driver.quit()
                        except Exception:
                            pass
                        driver = create_driver()
                        product_html = get_html(full_link, driver=driver)
                    found[full_link] = product_html

                psoup = BeautifulSoup(product_html, features="lxml")
                txt = psoup.get_text()

                # Prices
                sale_node = product.select_one(".price-item--sale, .price--sale")
                regular_node = product.select_one(
                    ".price-item--compare, .price-item--regular, .price--regular, .price, "
                    ".products-section-card-price .woocommerce-Price-amount"
                )
                sale_price_str = sale_node.get_text(strip=True) if sale_node else None
                reg_price_str = regular_node.get_text(strip=True) if regular_node else None

                product_id = get_product_id(company, tag)
                print(f"PRODUCT {title} [{tag}]")
                print(f"{'EXISTS' if product_id else 'NEW'} {tag}; parsing current product metadata")

                # Rating & votes
                rating_tag = product.select_one(".loox-rating")
                rating = rating_tag.get("data-rating") if rating_tag else None
                votes = rating_tag.get("data-raters") if rating_tag else None


                # Images
                image_list = []
                
                # Find all <img> tags
                for img in product.find_all("img"):
                    img_url = img.get("data-src") or img.get("src")
                    if not img_url:
                        continue
                    if img_url.startswith('//'):
                        img_url = 'https:' + img_url
                    img_alt = img.get("alt", "").strip()
                    if img_url:
                        image_list.append({"url": img_url, "alt": img_alt})

                valid_image_list = []
                img_n = 0
                for i in image_list:
                    img_n += 1
                    img_path = f'{tag}_{img_n}'
                    img = download_image(
                        i['url'],
                        img_path,
                        save_dir=f'data_from_sites_v2/{company}_images',
                        alt=i['alt'],
                        referer=full_link,
                        cookies={cookie['name']: cookie['value'] for cookie in driver.get_cookies()},
                    )
                    if img:
                        valid_image_list.append(img)
                print(f'Downloaded {len(valid_image_list)}/{len(image_list)} images for {tag}')



                # WooCommerce product pages do not always use Shopify's
                # MainContent wrapper. Use the full document as a safe
                # fallback so a missing wrapper does not abort the product.
                main_element = psoup.find("main", {"id": "MainContent"}) or psoup
                flavor_list = extract_options_generic(main_element, ["flavor", "flavours", "flavour", "flavors", "flavor profile", "taste", "taste profile", "choose your flavor", "choose your flavour", "flavor options", "flavour options", "flavor selection", "flavour selection", "available flavors", "available flavours", "flavor choices", "flavour choices", "flavor selection", "flavour selection"])
                colors = extract_options_generic(main_element, ["colors", "color", "choose your color", "choose your colours", "color options", "colour options", "color selection", "colour selection", "available colors", "available colours", "color choices", "colour choices", "available color", "available colour", "color variants", "colour variants", "color variations", "colour variations"])
                nicotine_strengths_ = extract_options_generic(main_element, ["nicotine strength", "nicotine strengths", "nicotine level", "nicotine levels", "nicotine content", "nicotine contents", "nicotine options", "nicotine selection", "nicotine choices", "nicotine variants", "nicotine variations"])
                nicotine_strengths = []
                for ns in nicotine_strengths_:
                    if ns:
                        # Split by common delimiters and normalize
                        match = re.match(r"(\d+(?:\.\d+)?)(.*)", ns.strip())
                        if match:
                            ns_num = match.group(1)
                            ns_text = match.group(2).strip()
                            if ns_num:
                                # Normalize to dict format
                                nicotine_strengths.append({'value': ns_num, 'unit': ns_text, 'level': None})
                bottle_sizes = extract_options_generic(main_element, ["bottle size", "bottle sizes", "size", "sizes", "volume", "volumes", "capacity", "capacities", "liquid volume", "liquid volumes", "e-liquid volume", "e-liquid volumes", "vape juice volume", "vape juice volumes"])  


                product_section = psoup.select_one('[data-section-type="product"]')
                description_div = psoup.find('div', class_='shopify-section product-description-section')
                if description_div:
                    description = description_div.get_text(" ", strip=True)
                else:
                    description = ''

                specs = extract_section_text(description_div, ["specifications", "specs", "features", "product features", "technical specifications", "technical specs", "product specifications"])
                package_contents = extract_section_text(description_div, ["package contents", "what's included", "what is included", "included items", "in the box", "in the package", "package includes", "box contents"])
                warnings_text = extract_section_text(description_div, ["warnings", "safety warnings", "safety information", "health warnings", "product warnings", "usage warnings", "caution", "important safety information", "safety precautions"])
                flavor_details = extract_section_text(description_div, ["flavor details", "flavor description", "flavour details", "flavour description", "taste description", "taste details", "flavor profile details", "flavour profile details", "flavor descriptions"])
                
                if not description or description == '':
                    description = specs + ' ' + package_contents + ' ' + warnings_text + ' ' + flavor_details
                    
                reviews = get_reviews(psoup)
                


                product_data = {
                    'tag': tag,
                    "title": title,
                    "brand": '',
                    "link": full_link,
                    "sale_price": sale_price_str,
                    "regular_price": reg_price_str,
                    'flavor_list': flavor_list, #list
                    'flavor_text': flavor_details, #str
                    'color_list': colors, #list
                    'nicotine_strengths': nicotine_strengths, #list
                    'bottle_sizes': bottle_sizes, #list
                    "stock_status": '',
                    'site_category': site_section,
                    'images': valid_image_list,
                    'html': product_html,
                    'plain_text': txt,
                    'description': description,
                    'sku': '',
                    'nicotine_strength': '',
                    'power_level': '',
                    'battery': '',
                    'coil': '',
                    'puffs': '',
                    'eliquid_contents': '',
                    'warnings': warnings_text,
                    'ingredients': '',
                    'features': specs,
                    'package_contents': package_contents,
                    'reviews': reviews
                }

                feats = list()
                #print(desc_fields)
                feat = find_features(description)
                any_found, puffs_res, nico_res, ml_res, flav_text, dev_text = feat
                product_data['puffs'] = puffs_res
                product_data['nicotine_strength'] = nico_res
                product_data['eliquid_contents'] = ml_res
                if any_found:
                    #print(feat)
                    feats.append(feat)
                disposable,recharge,battery,mesh,usb,adjustable,found_flavs = features_to_cats(feats)
                product_data['disposable_bool'] = disposable
                product_data['rechargeable_bool'] = recharge
                product_data['battery_bool'] = battery
                product_data['mesh_bool'] = mesh
                product_data['usb_bool'] = usb
                product_data['adjustable_bool'] = adjustable
                
                if product_id:
                    sync_ecig_product_history(product_id, product_data)
                    update_ecig_product_metadata(product_id, stable_sku(company, tag), product_data['stock_status'])
                    insert_reviews(reviews, product_id)
                    insert_ecig_price(product_id, reg_price_str, sale_price_str)
                else:
                    print('MAP PRODUCT DATA', top_level_link)
                    map_product_data(company, product_data)

    finally:
        try:
            driver.quit()
        except Exception:
            # The browser may already have exited after a WebDriver failure.
            pass

if __name__ == "__main__":
    print('get new products')
    main()
