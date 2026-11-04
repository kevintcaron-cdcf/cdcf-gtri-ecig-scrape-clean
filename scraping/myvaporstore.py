# import spacy
# import en_core_web_sm
# nlp = en_core_web_sm.load()

import requests
from bs4 import BeautifulSoup, element
import time
import pandas as pd
import random
import csv
import sys
import os
import json
import re
from typing import Optional, Any, Dict, List, Union

from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from db.db_azure import *
from ecig_parsing import *


BASE = 'https://www.myvaporstore.com' 
SITE = MY_VAPOR_STORE

links = [
    # Current top-level links from the MyVaporStore megamenu.
    '/New-Arrivals-Vape-s/77.htm',
    '/Shop-by-Brand-s/194.htm',
    '/E-Cig-Starter-Kits-E-Cigarette-s/70.htm',
    '/Accessories-s/207.htm',
    '/Dry-Herb-Oil-Wax-Vaporizer-s/621.htm',
    '/Vape-Clearance-Sale-s/398.htm',
      '/Disposable-Vapes-s/885.htm',
    '/Disposables-Prefilled-Carts-s/1116.htm',
    '/Sale-Disposables-s/1134.htm',
    '/Best-Selling-Ejuice-s/1163.htm', '/Best-Selling-Ejuice-s/1163.htm', 
    '/Best-Selling-Ejuice-s/1163.htm', '/Naked-100-E-Liquid-s/447.htm', 
    '/Freebase-E-liquids-s/1062.htm', '/Nicotine-Salt-Eliquid-s/633.htm', 
    '/Apple-Flavored-eLiquid-s/299.htm', '/Bakery-and-Desserts-eLiquid-s/291.htm', '/Banana-Flavored-eLiquid-s/301.htm', '/Berries-Flavored-eLiquid-s/302.htm', '/Caramel-eLiquid-s/310.htm', '/SearchResults.asp?Search=cereal', '/Cherry-Flavored-eLiquid-s/300.htm', '/Chocolate-eLiquid-s/306.htm', '/Cinnamon-eLiquid-s/308.htm', '/Citrus-Flavored-eLiquid-s/297.htm', '/Coconut-Flavored-eLiquid-s/295.htm', '/Coffee-and-Tea-eLiquid-s/292.htm', '/Custards-and-Creams-eLiquid-s/293.htm', '/Freebase-E-liquids-s/1062.htm', '/Fruit-eLiquid-s/307.htm', '/Grape-Flavored-eLiquid-s/303.htm', '/Lemonade-eLiquid-Flavors-s/570.htm', '/Mango-Flavored-eLiquid-s/304.htm', '/Melons-Flavored-eLiquid-s/298.htm', '/Menthol-Mint-Flavors-eLiquid-s/54.htm', '/Nicotine-Salt-Eliquid-s/633.htm', '/Peach-Flavored-eLiquid-s/305.htm', '/Strawberry-Flavor-eLiquid-s/294.htm', '/Tobacco-Flavors-eLiquid-s/53.htm', '/Tobacco-Free-Nicotine-s/1022.htm', '/Vanilla-eLiquid-s/309.htm', '/Watermelon-Flavored-eLiquid-s/296.htm', 
    '/eLiquids-by-Flavor-s/290.htm',
    '/sale-eliquids-s/1133.htm',
    '/Box-Mod-Ecig-Starter-Kits-s/523.htm',
    '/Pen-Style-Ecig-Starter-Kits-s/524.htm',
    '/Pod-Systems-Ecig-Starter-Kits-s/525.htm',
    '/E-Cig-Starter-Kits-E-Cigarette-s/70.htm', 
    '/Vape-Brands-Aspire-s/155.htm', '/Digiflavor-Ecig-Tanks-s/569.htm', 
    '/category-s/1074.htm', '/Efest-Batteries-and-Chargers-s/340.htm', 
    '/iSmoka-Eleaf-iStick-Box-Mod-s/224.htm', 
    '/FreeMax-Ecig-Products-s/683.htm', '/GeekVape-s/406.htm',
      '/Hamilton-Devices-s/1026.htm', '/E-Cigarette-Brands-Innokin-s/135.htm', 
      '/Joyetech-E-Cig-Brands-s/138.htm', '/Kangertech-E-Cigarettes-s/143.htm', 
      '/E-Cig-Brands-OVNS-s/666.htm', '/RELX-Ecig-Products-s/941.htm', 
      '/SMOK-VAPES-and-Accessories-s/159.htm', '/Suorin-Ecig-Products-s/583.htm',
        '/Tyson-Disposables-s/1148.htm', '/UWELL-Crown-Ecig-Tanks-and-Mods-s/374.htm',
          '/Vandy-Vape-Ecig-RDA-and-RTA-s/532.htm', '/Vaporesso-s/424.htm',
            '/Voopoo-Ecig-Mods-s/552.htm', '/Yocan-s/663.htm', 
            '/Yocan-Products-s/673.htm', '/E-Cig-Brands-iJoy-s/471.htm',
    '/Shop-by-Brand-s/194.htm', 
        '/Hemp-Vape-Kits-s/1184.htm', 
    '/Hemp-Disposables-s/1182.htm', 
    '/Hemp-Edibles-Rolls-s/1183.htm', 
    '/Alternative-Glass-Pipes-Bubblers-s/1115.htm', 
    '/Hemp-Accessories-s/1186.htm', 
    '/Hemp-Cartridges-Pods-s/1185.htm', 
    '/Dry-Herb-Oil-Wax-Vaporizer-s/621.htm', 
    '/Vape-Tanks-E-Cigarette-s/65.htm',
    '/official-myvaporstore-apparel-s/357.htm',
    '/Batteries-E-Cigarette-s/24.htm',
    '/Battery-Cases-E-Cigarette-s/548.htm',
    '/Bottles-E-Cigarette-s/25.htm',
    '/ECig-Chargers-s/221.htm',
    '/Drip-Tips-E-Cigarette-s/68.htm',
    '/Miscellaneous-s/29.htm',
    '/Replacement-Coils-and-pod-cartridges-s/163.htm',
    '/thread-adapters-for-ecig-s/60.htm',
    '/sale-Hardware-s/1140.htm',
    '/Sale-Herbal-Alternative-Products-s/1145.htm',
    '/Wick-Wire-s/164.htm',
    '/Accessories-s/207.htm', 
    '/New-Arrivals-Vape-s/77.htm', 
    '/Vape-Clearance-Sale-s/398.htm'
]


print('TOTAL LINKS', len(links))
found = dict()

def normalize_space(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    return re.sub(r"\s+", " ", s).strip()

def _is_heading_like(el) -> bool:
    if not el or not getattr(el, "name", None):
        return False
    if el.name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        return True
    # role="heading" on any tag (e.g., strong/span/div)
    if el.has_attr("role") and el["role"].lower() == "heading":
        return True
    return False

def _nearest_heading_text(el) -> Optional[str]:
    """
    Walks previous siblings and parents to find a nearby heading-like label.
    """
    # 1) check previous siblings in the same container
    sib = el.previous_sibling
    while sib:
        try:
            if _is_heading_like(sib):
                return normalize_space(sib.get_text(" ", strip=True))
            # also check if sibling contains a heading inside
            inner = sib.find(True) if hasattr(sib, "find") else None
            if inner and _is_heading_like(inner):
                return normalize_space(inner.get_text(" ", strip=True))
        except Exception:
            pass
        sib = getattr(sib, "previous_sibling", None)

    # 2) climb ancestors and look for a heading within that ancestor
    for anc in el.parents:
        if not getattr(anc, "name", None):
            continue
        # first, direct heading child
        for child in anc.find_all(True, recursive=False):
            if _is_heading_like(child):
                return normalize_space(child.get_text(" ", strip=True))
        # fallback: any heading inside the ancestor
        hit = anc.find(attrs={"role": re.compile(r"^heading$", re.I)})
        if hit:
            return normalize_space(hit.get_text(" ", strip=True))
        for htag in ("h1","h2","h3","h4","h5","h6"):
            hit = anc.find(htag)
            if hit:
                return normalize_space(hit.get_text(" ", strip=True))
    return None

def get_options_by_keywords(root, keywords: List[str]) -> List[str]:
    """
    Extract option values (e.g., flavors/colors/sizes) using nearby heading-like labels
    or data attributes. Does not rely on <label>.
    """
    if not root:
        return []

    keywords_lower = [k.lower() for k in keywords]
    results = set()

    def _matches_heading(text: Optional[str]) -> bool:
        if not text:
            return False
        low = text.lower()
        return any(k in low for k in keywords_lower)

    # ---- 1) <select> blocks with a nearby heading-like element ----
    for sel in root.select("select"):
        heading_txt = _nearest_heading_text(sel)
        # also consider name/aria-label if present
        name_attr = (sel.get("name") or "").lower()
        aria_label = (sel.get("aria-label") or "").lower()
        if _matches_heading(heading_txt) or any(k in name_attr or k in aria_label for k in keywords_lower):
            for opt in sel.find_all("option"):
                val = normalize_space(opt.get_text())
                if val and not re.search(r"\b(choose|select|pick|option)\b", val, re.I):
                    results.add(val)

    # ---- 2) Swatch-style groups (buttons/divs) under a labeled container ----
    # common patterns: lists of buttons/spans inside a container; find the group, then locate its heading
    # We'll look at clickable items that carry a value in data-*, aria-label, title, or text.
    for candidate in root.select(
        "[data-option-name], [data-option-value], [data-value], [role=radio], button, .swatch, .variant, .option"
    ):
        # find a nearby heading for the group container (prefer parent group)
        group = candidate
        for _ in range(3):  # climb up a few levels to hit the group wrapper
            group = group.parent if group and getattr(group, "parent", None) else group
        group = group or candidate
        heading_txt = _nearest_heading_text(group) or _nearest_heading_text(candidate)
        data_name = (candidate.get("data-option-name") or "").lower()
        if _matches_heading(heading_txt) or any(k in data_name for k in keywords_lower):
            # extract the value
            raw = (
                candidate.get("data-option-value")
                or candidate.get("data-value")
                or candidate.get("aria-label")
                or candidate.get("title")
                or candidate.get_text(" ", strip=True)
            )
            val = normalize_space(raw)
            if val and not re.fullmatch(r"\s*", val):
                results.add(val)

    # ---- 3) Generic list items under a heading (e.g., <ul><li>...) ----
    # Find heading-like nodes that match, then gather simple child items following them.
    for heading in root.select("[role=heading], h1, h2, h3, h4, h5, h6, strong[role=heading], span[role=heading]"):
        if not _matches_heading(heading.get_text(" ", strip=True)):
            continue
        # look for sibling/descendant lis/buttons/spans that look like options
        container = heading.parent if heading.parent else heading
        for opt_node in container.find_all(["li", "button", "span", "a", "div"], limit=200):
            if opt_node is heading:
                continue
            txt = normalize_space(opt_node.get_text(" ", strip=True))
            if not txt:
                continue
            # heuristics: avoid long sentences; skip prompts
            if len(txt) > 60:
                continue
            if re.search(r"\b(choose|select|pick|option)\b", txt, re.I):
                continue
            # require that node looks like an option: has role, data-*, or is inside a list/grid
            if (
                opt_node.has_attr("role")
                or any(attr in opt_node.attrs for attr in ["data-option-value", "data-value", "data-variant"])
                or opt_node.name in {"li", "button"}
            ):
                results.add(txt)

    return sorted(results)


def get_driver():
    options = Options()
    if os.environ.get("HEADLESS", "0").lower() not in {"0", "false", "no"}:
        options.add_argument('--headless')
    driver = webdriver.Firefox(options=options)
    driver.set_page_load_timeout(120)
    return driver


def get_html(url, clicked=True, closed=True, elements=True, driver=None):

    owns_driver = driver is None
    try:
        if owns_driver:
            driver = get_driver()
        driver.get(url)
        last_n = 0
        hrefs = set()
        button_id = 'ac-ag-yes-button'

        html = driver.page_source
        time.sleep(1)
        same_count = 0

        # wait = WebDriverWait(driver, 10) 
        # wait.until(EC.visibility_of_element_located((By.CLASS_NAME, "modal-content")))

        if not clicked:
            try:
                button = WebDriverWait(driver, 3).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(., '21') or contains(., 'Yes')]")
                ))
                button.click()
            except TimeoutException:
                pass

        if not closed:
            wait = WebDriverWait(driver, 3)  # 10 seconds timeout
            button = wait.until(EC.element_to_be_clickable((By.CLASS_NAME, 'close')))  # Use ID, XPATH, or other locator

            # Click the button
            button.click()
            closed = True
    

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
        html = driver.page_source

    except Exception as ex:
        print(ex)
        html = ''
    finally:
        if driver and owns_driver:
            driver.quit()
    time.sleep(3)


    return html


def download_product_images(soup, tag):
    """Download gallery images so existing products can be backfilled."""
    records = []
    seen = set()
    gallery = soup.select_one(
        '[data-product-gallery], .product-gallery, .productView-images, '
        '.w-100.pa2'
    ) or soup
    for image in gallery.select('img'):
        src = image.get('data-zoom-image') or image.get('data-src') or image.get('src')
        if not src and image.get('srcset'):
            src = image['srcset'].split(',')[-1].strip().split(' ')[0]
        if not src:
            continue
        src = requests.compat.urljoin(BASE, src)
        if src in seen or src.startswith('data:') or 'logo' in src.lower():
            continue
        seen.add(src)
        saved = download_image(
            src,
            tag,
            save_dir=f'data_from_sites_v2/{SITE}_images',
            alt=image.get('alt', ''),
            number_append=len(records) + 1,
            referer=BASE,
        )
        if saved:
            records.append(saved)
    return records

if __name__ == "__main__":
    """
    from collections import Counter

    product_list = list()
    all_headers = list()
    header_counter = Counter(all_headers)
    header_samples = dict()
    
    has_header = False
    
    driver = get_driver()
    try:
        homepage = requests.get(BASE, timeout=45)
        discovered = discover_catalog_links(
            homepage.text,
            BASE,
            prefixes=("/",),
            exclude=("/cart", "/login", "/account", "/search", "/compare", "/blog", "/help"),
        )
        scrape_links = list(dict.fromkeys(links + discovered))
        print(f"Discovered {len(discovered)} My Vapor Store catalog links; using {len(scrape_links)} total")
        for top_level_link in prioritize_links(scrape_links):
            page = 1
            site_section = normalize_site_category(top_level_link)
            while True:
                url = f'{BASE}{top_level_link}?page={page}'
                print(url)

                if url in found:
                    reqtxt = found[url]
                else:
                    reqtxt = get_html(url, driver=driver)
                    found[url] = reqtxt
            #reqtxt = get_html(url)
                soup = BeautifulSoup(reqtxt)
                products = soup.select(
                'div.pa2.w-100.pt2.ph2.pb3.ph3-ns.pb4-ns.tl, '
                '[data-product-id], [data-product], .product-card'
            )
                print(url, len(products))
                if not products and len(reqtxt) < 1000:
                    print(f"My Vapor Store returned an empty/blocked page ({len(reqtxt)} bytes): {url}")
            
                if len(products) == 0:
                    break
                page += 1

                for product_card in products:
                    if not isinstance(product_card, element.Tag):
                        continue

                    product_name = product_card.find('h4')
                if product_name:
                    title = product_name.get_text(strip=True)
                
                # Extract brand
                    brand_card = product_card.find('div', {'data-brand': True})
                if brand_card:
                    brand = brand_card.get_text(strip=True)

                    tag = ''
                    product_link = product_card.find('a', href=True)
                if product_link:
                    product_url_path = product_link.get('href')
                    full_link = f'{BASE}{product_url_path}'
                    tag = product_url_path.split('/')[-1].split('.htm')[0]

                # Extract pricing information
                    base_price = product_card.find('div', {'data-product-base-price': True})
                if base_price:
                    price_text = base_price.get_text(strip=True)
                    reg_price_str = re.sub(r'[^\d.]', '', price_text)
                
                    sale_price = product_card.find('div', {'data-product-sale-price': True})
                if sale_price:
                    price_span = sale_price.find('span', class_='_dqivtj')
                    if price_span:
                        price_text = price_span.get_text(strip=True)
                        sale_price_str = re.sub(r'[^\d.]', '', price_text)

                    product_id = get_product_id(MY_VAPOR_STORE, tag)
                    if product_id:
                        print('EXISTS', tag)
                        image_records = download_product_images(
                            BeautifulSoup(get_html(full_link, driver=driver), 'lxml'), tag
                        )
                        insert_product_images(product_id, image_records)
                        insert_ecig_price(product_id, reg_price_str, sale_price_str)

                    continue



                    stock_status = product_card.find('strong', {'data-product-stock-status': True})
                if stock_status:
                    stock_status_str = stock_status.get_text(strip=True)

                    print(full_link)

                    if full_link in found:
                        product_html = found[full_link]
                    else:
                        product_html = get_html(full_link, driver=driver)
                        found[full_link] = product_html

                    psoup = BeautifulSoup(product_html)
                    txt = psoup.get_text()

                    main_element = psoup.find('div', class_='w-100 pa2')
                    if not main_element:
                        print('NO MAIN ELEMENT', full_link)
                        continue

                    flavor_list = get_options_by_keywords(main_element, ["flavor", "flavors", "flavor list", "available flavors"])
                    colors = get_options_by_keywords(main_element, ["color", "colors", "color list", "available colors"])

                    nicotine_strengths = get_options_by_keywords(main_element, ["nicotine strength", "nicotine strengths", "nicotine level", "nicotine levels"])
                    bottle_sizes = get_options_by_keywords(main_element, ["bottle size", "bottle sizes", "size", "sizes", "ml", "milliliter", "milliliters"])
                
                    image_list = []

                # Find all <img> tags
                    for img in main_element.find_all("img"):
                    img_url = img.get("src")
                    img_alt = img.get("alt", "").strip()
                    if url:
                        image_list.append({"url": img_url, "alt": img_alt})

                    valid_image_list = []
                    img_n = 0
                    for i in image_list:
                    img_n += 1
                    img_path = f'{tag}_{img_n}'
                    img = download_image(i['url'], img_path, save_dir=f'data_from_sites_v2/{SITE}_images', alt=i['alt'])
                    if img:
                        valid_image_list.append(img)
                print(f'Downloaded {len(valid_image_list)}/{len(image_list)} images for {tag}')

                # Look for description container
                    desc_elem = main_element.find(attrs={"data-clicktarget": "descriptionPosition"})

                    description = ""
                if desc_elem:
                    # Get all text without tags
                    description = desc_elem.get_text(separator=" ", strip=True)


                    warnings_text = ""

                # Find the "Warnings" section
                    warnings_section = main_element.find("h4", string=lambda t: t and "Warnings" in t)
                    if warnings_section:
                    # The text is inside the next sibling div
                    parent_btn = warnings_section.find_parent("button")
                    if parent_btn:
                        content_div = parent_btn.find_next_sibling("div")
                        if content_div:
                            warnings_text = content_div.get_text(separator=" ", strip=True)

                    features_specs = []

                # Find the "Features and Specs" heading
                    features_heading = main_element.find("h5", string=lambda t: t and "Features and Specs" in t)
                    if features_heading:
                    # The <ul> with the list is right after the heading
                    ul = features_heading.find_next("ul")
                    if ul:
                        for li in ul.find_all("li"):
                            text = li.get_text(strip=True)
                            if text:
                                features_specs.append(text)

                    package_contents = ""

                # Find the "Package Contents" heading
                    pkg_heading = main_element.find("h4", string=lambda t: t and "Package Contents" in t)
                    if pkg_heading:
                    parent_btn = pkg_heading.find_parent("button")
                    if parent_btn:
                        content_div = parent_btn.find_next_sibling("div")
                        if content_div:
                            package_contents = content_div.get_text(separator=" ", strip=True)
                    reviews = []

                # Find review containers (adjust selector based on actual HTML structure)
                    for review in psoup.select('[data-product-review]'):
                    date = None
                    author = None
                    review_text = None
                    stars = None

                    # Date
                    date_tag = review.find(attrs={"data-review-date": True})
                    if date_tag:
                        date = date_tag.get_text(strip=True)

                    # Author
                    author_tag = review.find(attrs={"data-review-author": True})
                    if author_tag:
                        author = author_tag.get_text(strip=True)

                    # Review text
                    text_tag = review.find(attrs={"data-review-text": True})
                    if text_tag:
                        review_text = text_tag.get_text(strip=True)

                    # Stars - count star icons or read data attribute
                    stars_tag = review.find(attrs={"data-review-rating": True})
                    if stars_tag:
                        try:
                            stars = int(stars_tag["data-review-rating"])
                        except:
                            # fallback: count filled star icons
                            stars = len(stars_tag.select('.fa-star'))

                    reviews.append({
                        "date": date,
                        "author": author,
                        "review_text": review_text,
                        "stars": stars
                    })



                # Extracting product information
                    product_data = {
                    'tag': tag,
                    "title": title,
                    "brand": brand,
                    "link": full_link,
                    "sale_price": sale_price_str,
                    "regular_price": reg_price_str,
                    'flavor_list': flavor_list, #list
                    'flavor_text': '', #str
                    'color_list': colors, #list
                    'nicotine_strengths': nicotine_strengths, #list
                    'bottle_sizes': bottle_sizes, #list
                    "stock_status": stock_status_str if stock_status else '',
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
                    'features': '\n'.join(features_specs),
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
                
                    print('MAP PRODUCT DATA', top_level_link, )
                    map_product_data(MY_VAPOR_STORE, product_data)
    finally:
        driver.quit()
    """

    driver = get_driver()
    try:
        for top_level_link in links:
            site_section = normalize_site_category(top_level_link)
            page = 1
            while True:
                url = f'{BASE}{top_level_link}?page={page}'
                print(url)
                reqtxt = found.get(url) or get_html(url, driver=driver)
                found[url] = reqtxt
                soup = BeautifulSoup(reqtxt, 'lxml')
                products = soup.select(
                    'div.pa2.w-100.pt2.ph2.pb3.ph3-ns.pb4-ns.tl, '
                    '[data-product-id], [data-product], .product-card'
                )
                print(url, len(products))
                if not products:
                    break

                for product_card in products:
                    product_link = product_card.find('a', href=True)
                    title_node = product_card.find(['h4', 'h3', 'h2'])
                    if not product_link or not title_node:
                        continue
                    product_url_path = product_link.get('href')
                    full_link = requests.compat.urljoin(BASE, product_url_path)
                    tag = product_url_path.split('/')[-1].split('.htm')[0]
                    title = title_node.get_text(' ', strip=True)
                    brand_node = product_card.find(attrs={'data-brand': True})
                    brand = brand_node.get_text(' ', strip=True) if brand_node else ''
                    price_node = product_card.find(attrs={'data-product-base-price': True})
                    regular_price = re.sub(r'[^\d.]', '', price_node.get_text(strip=True)) if price_node else ''
                    stock_node = product_card.find('strong', {'data-product-stock-status': True})
                    stock_status = stock_node.get_text(strip=True) if stock_node else ''

                    product_html = found.get(full_link) or get_html(full_link, driver=driver)
                    found[full_link] = product_html
                    product_soup = BeautifulSoup(product_html, 'lxml')
                    main_element = product_soup.find('div', class_='w-100 pa2') or product_soup
                    description = main_element.get_text(' ', strip=True)
                    data = {
                        'tag': tag,
                        'title': title,
                        'brand': brand,
                        'link': full_link,
                        'sale_price': None,
                        'regular_price': regular_price,
                        'flavor_list': [],
                        'flavor_text': '',
                        'color_list': [],
                        'nicotine_strengths': [],
                        'bottle_sizes': [],
                        'stock_status': stock_status,
                        'site_category': site_section,
                        'images': [],
                        'html': product_html,
                        'plain_text': product_soup.get_text(' ', strip=True),
                        'description': description,
                        'sku': '',
                        'nicotine_strength': '',
                        'power_level': '',
                        'battery': extract_battery(description),
                        'coil': '',
                        'puffs': '',
                        'eliquid_contents': '',
                        'warnings': '',
                        'ingredients': '',
                        'features': '',
                        'package_contents': '',
                        'reviews': extract_reviews(product_soup),
                        'review_attributes': {},
                    }
                    any_found, puffs, nicotine, liquid, _, _ = find_features(description)
                    data['puffs'] = puffs
                    data['nicotine_strength'] = nicotine
                    data['eliquid_contents'] = liquid
                    data['images'] = download_product_images(product_soup, tag)
                    print(f"Downloaded {len(data['images'])} images for {tag}")
                    product_id = get_product_id(MY_VAPOR_STORE, tag)
                    if product_id:
                        print(f'EXISTS {tag}; recording price history')
                        sync_ecig_product_history(product_id, data)
                        update_ecig_product_metadata(product_id, stable_sku(MY_VAPOR_STORE, tag))
                        reviews = extract_reviews(product_soup)
                        print(f"REVIEWS {tag}: {len(reviews)} found" if reviews else f"REVIEWS {tag}: none found")
                        if reviews:
                            insert_reviews(reviews, product_id)
                        if not product_has_images(product_id):
                            insert_product_images(product_id, download_product_images(product_soup, tag))
                        else:
                            print(f"IMAGES EXIST for product_id {product_id}; skipping image download")
                        insert_ecig_price(product_id, regular_price, None)
                    else:
                        print(f'NEW {tag}; inserting product and initial price history')
                        print(f"REVIEWS {tag}: {len(data['reviews'])} found" if data["reviews"] else f"REVIEWS {tag}: none found")
                        map_product_data(MY_VAPOR_STORE, data)
                page += 1
    finally:
        driver.quit()
