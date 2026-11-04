# import spacy
# import en_core_web_sm
# nlp = en_core_web_sm.load()

import requests
import re
from bs4 import BeautifulSoup, element
import time
import pandas as pd
import random
import csv
import sys
import os
import json
import re

from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from db.db_azure import *
from ecig_parsing import *


BASE = 'https://csvape.com' # https://csvape.com/collections/7-daze-salt-nicotine

links = [
# DISPOSABLE VAPES (PRIORITY)
    "/collections/disposable-vapes",
    "/collections/geek-bar",
    "/collections/flum",
    "/collections/lost-mary",
    "/collections/adjust-brand",
    "/collections/raz-vapes",
    "/collections/foger?sort_by=best-selling&filter.p.m.custom.categories=Disposable",
    "/collections/spaceman",
    "/collections/swft",
    "/collections/al-fakher",
    "/collections/my-shisha-disposable-vapes",
    "/collections/starbuzz",
    
    # Disposable by Flavor Profile
    "/collections/fruit-flavor-disposable-vapes",
    "/collections/candy-flavor-dispsoable-vapes",
    "/collections/menthol-flavor-disposable-vapes",
    "/collections/dessert-flavor-disposable-vapes",
    "/collections/tobacco-flavor-disposable-vape",
    "/collections/clear-flavor-disposable-vape",
    
    # Disposable by Nicotine Strength
    "/collections/50mg-nicotine-disposable-vape",
    "/collections/20mg-nicotine-disposable-vape",
    "/collections/zero-nicotine-disposable-vape",
    
    # Disposable by Puff Count
    "/collections/50k-puffs-disposable-vapes",
    "/collections/40000-puffs-disposable-vapes",
    "/collections/30000-puffs-disposable-vapes",
    "/collections/25000-puffs-disposable-vapes",
    "/collections/20000-puff-disposable-vapes",
    "/collections/15000-puff-disposable-vapes",
    "/collections/10000-puff-disposable-vapes",
    "/collections/5000-puffs-disposable-vapes",
    
    # Disposable by Features
    "/collections/freebase-disposable-vape",
    "/collections/rechargeable-disposable-vapes",
    "/collections/lcd-screen-disposable-vapes",
    "/collections/mode-changing-disposable-vapes",
    
    # NEW ARRIVALS
    "/collections/newarrivals",
    
    # ELIQUIDS
    "/collections/eliquid",
    "/collections/salt-nicotine-ejuice",
    "/collections/freebase-nicotine-ejuice-brands",
    
    # Eliquid by Flavor (Salt Nic)
    "/collections/fruity-flavors-e-liquid?sort_by=best-selling&filter.p.m.custom.ejuice_type=Salt+Nicotine",
    "/collections/candy-flavors-e-liquid?sort_by=best-selling&filter.p.m.custom.ejuice_type=Salt+Nicotine",
    "/collections/menthol-flavors-e-liquid?sort_by=best-selling&filter.p.m.custom.ejuice_type=Salt+Nicotine",
    "/collections/dessert-flavors-e-liquid?sort_by=best-selling&filter.p.m.custom.ejuice_type=Salt+Nicotine",
    "/collections/tobacco-flavors-e-liquid?sort_by=best-selling&filter.p.m.custom.ejuice_type=Salt+Nicotine",
    
    # Eliquid by Flavor (Freebase)
    "/collections/fruity-flavors-e-liquid?sort_by=best-selling&filter.p.m.custom.ejuice_type=Freebase",
    "/collections/candy-flavors-e-liquid?sort_by=best-selling&filter.p.m.custom.ejuice_type=Freebase",
    "/collections/menthol-flavors-e-liquid?sort_by=best-selling&filter.p.m.custom.ejuice_type=Freebase",
    "/collections/dessert-flavors-e-liquid?sort_by=best-selling&filter.p.m.custom.ejuice_type=Freebase",
    "/collections/tobacco-flavors-e-liquid?sort_by=best-selling&filter.p.m.custom.ejuice_type=Freebase",
    
    # Eliquid Brands
    "/collections/vgod-ejuice",
    "/collections/saltnic-labs",
    "/collections/monster-vape-labs",
    "/collections/juice-head-eliquid",
    "/collections/coastal-clouds",
    "/collections/the-mamasan",
    "/collections/7-daze-eliquid",
    "/collections/glas-basix-ejuice",
    "/collections/cloud-nurdz",
    "/collections/its-pixy-ejuice",
    "/collections/reds-ejuice",
    "/collections/four-seasons-salts",
    "/collections/naked-100",
    "/collections/vgod",
    
    # Eliquid by Nicotine Strength
    "/collections/50mg-nicotine-above-ejuice",
    "/collections/40mg-to-50mg-ejuice",
    "/collections/30mg-to-40mg-ejuice",
    "/collections/20mg-to-30mg-ejuice",
    "/collections/12mg-nicotine-eliquid",
    "/collections/6mg-nicotine-eliquid",
    "/collections/3mg-nicotine-eliquid",
    "/collections/zero-nicotine-eliquid",
    
    # VAPE KITS
    "/collections/vape-kits",
    "/collections/vape-starter-kits",
    "/collections/pod-systems",
    "/collections/box-mods",
    "/collections/vape-pen-kits",
    "/collections/boro-box-mods",
    
    # Vaporizers
    "/collections/vaporizers",
    "/collections/herbal-vaporizers",
    "/collections/concentrate-vaporizer",
    "/collections/vape-batteries",
    
    # Tanks & RDAs
    "/collections/tanks",
    "/collections/sub-ohm-tanks",
    
    # Accessories
    "/collections/vape-accessories",
    "/collections/tank-replacement-coils",
    "/collections/replacement-pods-pod-systems",
    "/collections/others",
    
    # Starter Kit Brands
    "/collections/uwell-starter-kits",
    "/collections/smok-vape-starter-kits",
    "/collections/geek-vape-vape-starter-kits",
    "/collections/voopoo-vape-starter-kits",
    
    # Vaporizer Brands
    "/collections/yocan-vaporizers",
    "/collections/lookah-vaporizers",
    "/collections/grenco-science",
    
    # Tank Brands
    "/collections/geekvape?sort_by=best-selling&filter.p.m.custom.categories=Tanks",
    "/collections/smok-tanks",
    "/collections/ofrf",
    "/collections/vaporesso-tanks",
    "/collections/voopoo-tanks",
    "/collections/horizon?sort_by=best-selling&filter.p.m.custom.categories=Tanks",
    
    # NICOTINE POUCHES
    "/collections/nicotine-pouches",
    
    # Nicotine Pouches by Type
    "/collections/moist-nicotine-pouches",
    "/collections/dry-nicotine-pouches",
    "/collections/semi-dry-nicotine-pouches",
    
    # Nicotine Pouches by Flavor
    "/collections/fruit-flavor-nicotine-pouches",
    "/collections/menthol-flavor-nicotine-pouches",
    "/collections/menthol-fruity-nicotine-pouches",
    "/collections/tobacco-flavor-nicotine-pouches",
    "/collections/coffee-flavor-nicotine-pouches",
    
    # Nicotine Pouch Brands
    "/collections/fre-nicotine-pouches",
    "/collections/zimo-nicotine-pouches",
    "/collections/zyn-nicotine-pouches",
    "/collections/zone-nicotine-pouches",
    "/collections/rogue-nicotine-pouches",
    "/collections/grizzly-nicotine-pouches",
    "/collections/velo-plus-nicotine-pouches",
    "/collections/chlz-nicotine-pouches",
    "/collections/lucy",
    "/collections/lucy-breakers",
    
    # Nicotine Pouches by Strength
    "/collections/3mg-nicotine-pouches",
    "/collections/4mg-nicotine-pouches",
    "/collections/6mg-nicotine-pouches",
    "/collections/8mg-nicotine-pouches",
    "/collections/9mg-nicotine-pouches",
    "/collections/12mg-nicotine-pouches",
    "/collections/15mg-nicotine-pouches",
    
    # Additional Brand Collections
    "/collections/hyppe"
]

print('TOTAL LINKS', len(links))
found = dict()

def extract_section_items(scope, keywords):
    """
    Finds a section whose heading/label matches any keyword in `keywords`,
    then returns a list of bullet/line items from the next list, table, or text block.
    """
    found = []

    def _push_many(text):
        # Split on bullets, line breaks, or commas (but not numbers like 1,000)
        parts = re.split(r"[•·\n]|,(?!\s*\d)", text)
        for p in parts:
            s = re.sub(r"\s+", " ", p).strip(" :\u00b7•·-").strip()
            if s:
                found.append(s)

    # Scan headings, summary elements, or strong/bold labels
    for h in scope.find_all(["h2", "h3", "h4", "summary", "button", "strong", "b"]):
        label = h.get_text(" ", strip=True).lower()
        if any(k in label for k in keywords):
            # Look for the next content block
            nxt = h.find_next(lambda t: t and t.name in ("ul","ol","div","p","table"))
            if nxt:
                if nxt.name in ("ul", "ol"):
                    for li in nxt.find_all("li"):
                        _push_many(li.get_text(" ", strip=True))
                elif nxt.name == "table":
                    for tr in nxt.find_all("tr"):
                        cells = tr.find_all(["td", "th"])
                        if cells:
                            _push_many(cells[0].get_text(" ", strip=True))
                else:
                    _push_many(nxt.get_text(" ", strip=True))

    # Remove duplicates, preserve order
    seen, out = set(), []
    for item in found:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            out.append(item)

    return '\n'.join(out)

def _clean(txt: str) -> str:
    # collapse whitespace and trim
    return re.sub(r"\s+\n", "\n", re.sub(r"[ \t]+", " ", txt)).strip()

def extract_description(scope) -> str:
    chunks = []

    # 1) JSON-LD Product.description (if present)
    for tag in scope.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or tag.get_text(strip=True))
        except Exception:
            continue
        objs = data if isinstance(data, list) else [data]
        for obj in objs:
            if isinstance(obj, dict) and obj.get("@type") == "Product":
                desc = obj.get("description")
                if isinstance(desc, str) and desc.strip():
                    chunks.append(desc.strip())

    # 2) Common description containers
    selectors = [
        "[data-product-description]",
        ".product__description",
        ".product-description",
        "#description",
        ".product-single__description",
        ".rte",          # many themes use rich-text editor class
        ".prose",        # tailwind prose blocks
    ]
    for sel in selectors:
        for el in scope.select(sel):
            txt = el.get_text(" ", strip=True)
            if txt:
                chunks.append(txt)

    # 3) Sections following headings like "Description", "Details", "Features"
    def looks_like_desc(s: str) -> bool:
        s = s.lower()
        return any(k in s for k in ("description", "details", "features", "about"))

    for h in scope.find_all(["h2","h3","h4","button","summary"]):
        label = h.get_text(" ", strip=True)
        if label and looks_like_desc(label):
            nxt = h.find_next(lambda t: t and t.name in ("div","section","article","p","ul","ol"))
            if nxt:
                txt = nxt.get_text(" ", strip=True)
                if txt:
                    chunks.append(txt)

    # Deduplicate while preserving order
    seen = set()
    out = []
    for chunk in chunks:
        c = _clean(chunk)
        if c and c not in seen:
            seen.add(c)
            out.append(c)

    # Join with blank lines to keep paragraphs readable
    return "\n\n".join(out)

def extract_options(scope, keywords):
    """
    Extracts option text for any <fieldset>/<select> whose legend/label 
    contains one of the given keywords.
    Returns a list of unique strings in order of appearance.
    """
    found = []

    # Fieldsets with matching legend
    for fs in scope.find_all("fieldset"):
        legend = fs.find("legend")
        if legend and any(k in legend.get_text(strip=True).lower() for k in keywords):
            for opt in fs.find_all(["option", "button", "label"]):
                txt = opt.get_text(strip=True)
                if txt and txt.lower() not in {"choose an option", "select"}:
                    found.append(txt)

    # Label + select pairs
    for lab in scope.find_all("label"):
        if any(k in lab.get_text(strip=True).lower() for k in keywords):
            sel = lab.find_next("select")
            if sel:
                for opt in sel.find_all("option"):
                    txt = opt.get_text(strip=True)
                    if txt and txt.lower() not in {"choose an option", "select"}:
                        found.append(txt)

def get_html(url, clicked=False, closed=True, elements=True):

    driver = None
    try:
        options = Options()
        options.add_argument('--headless')  # Enable headless mode properly

        # Start the WebDriver in headless mode
        driver = webdriver.Firefox(options=options)
        driver.get(url)
        last_n = 0
        hrefs = set()
        button_id = 'ac-ag-yes-button'

        html = driver.page_source
        time.sleep(1)
        same_count = 0
        if not clicked:
            wait = WebDriverWait(driver, 3)  # 10 seconds timeout
            button = wait.until(EC.element_to_be_clickable((By.ID, button_id)))  # Use ID, XPATH, or other locator

            # Click the button
            button.click()
            clicked = True
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
        if driver:
            driver.close()
    time.sleep(3)


    return html

def extract_options(scope, labels):
    """
    Returns a list of option texts for the first matching label in `labels`.
    Example:
        extract_select_options(main, ["Flavor", "Colour", "Color"])
    """
    labels_lower = [lbl.strip().lower() for lbl in labels]

    # Find the label element that matches any in the list
    label_el = scope.find("label", string=lambda s: s and s.strip().lower() in labels_lower)
    if not label_el:
        return []

    # Get the <select> element after the label
    select = label_el.find_next("select")
    if not select:
        return []

    # Collect the displayed text of each <option>
    return [opt.get_text(strip=True) for opt in select.find_all("option")]

def extract_product_images(scope):
    """
    Return [{'url': str, 'alt': str}, ...] from the main gallery
    (ignores thumbnails). Protocol-relative URLs ('//...') -> 'https://...'.
    """
    out, seen = [], set()

    gallery = scope.select_one(".product__gallery-container") or scope
    for img in gallery.select(".product__media-list img"):
        url = img.get("src") or img.get("data-src") or ""
        if not url and img.get("srcset"):
            # fallback: take last (largest) srcset candidate
            parts = [p.strip().split()[0] for p in img["srcset"].split(",") if p.strip()]
            url = parts[-1] if parts else ""

        if not url:
            continue

        if url.startswith("//"):
            url = "https:" + url  # assume https

        alt = (img.get("alt") or "").strip()

        # de-dupe by URL
        if url not in seen:
            seen.add(url)
            out.append({"url": url, "alt": alt})

    return out

if __name__ == "__main__":
    from collections import Counter

    product_list = list()
    all_headers = list()
    header_counter = Counter(all_headers)
    header_samples = dict()
    
    has_header = False
    
    with open('scraping/data-latest/csvape_scrape.csv', mode='w') as file:

        for top_level_link in links:
            page = 1
            site_section = normalize_site_category(top_level_link)

            url = f'{BASE}{top_level_link}'
            print('TOP LEVEL LINK', url)

            if url in found:
                reqtxt = found[url]
            else:
                reqtxt = get_html(url)
                found[url] = reqtxt
            #reqtxt = get_html(url)
            soup = BeautifulSoup(reqtxt)
            products = soup.find_all('div', {'class': 'product-card'})
            print(url, len(products))

            for p in products:
                if not isinstance(p, element.Tag):
                    continue
                title = p.find("a", class_="product-card__title").text.strip()
                link = p.find("a", class_="product-card__title")['href']
                spe = p.find("span", class_="price--highlight")
                rpe = p.find("span", class_="price__regular")
                sale_price = None
                reg_price = None


                if rpe:
                    rpe_txt = rpe.text.strip()
                else:
                    rpe_txt = None

                # if spe:
                #     sale_price = spe.text.strip().replace('Sale price', '')
                # else:
                #     sale_price = None
                if rpe_txt and 'Sale price' in rpe_txt:
                    sale_price = rpe_txt.replace('Sale price', '').strip()
                else:
                    reg_price = rpe_txt

                print(link)

                # if rpe:

                #     reg_price = rpe.text.strip().replace('Regular price', '')
                # else:
                #     reg_price = None


                tag = link.split('/')[-1].split('?')[0]

                if product_exists(CS_VAPE, tag):
                    print('EXISTS', tag)
                    continue
                full_link = f'{BASE}{link}'



                if full_link in found:
                    reqtxt = found[full_link]
                else:
                    # print(full_link)
                    reqtxt = get_html(full_link, elements=False)
                    found[full_link] = reqtxt
                psoup = BeautifulSoup(reqtxt)
                txt = psoup.get_text()

                main = psoup.find(id="MainContent") or psoup.find("main") or psoup
                if not main:
                    print('NO MAIN CONTENT', full_link)
                    continue
                
                media_container = main.select_one(".product__media-container")

                if not media_container:
                    images = []
                else:
                    # Extract images
                    img_urls = extract_product_images(media_container)

                    n = 0
                    images = list()
                    for i in img_urls:
                        n += 1
                        img = download_image(i['url'], tag, save_dir='data_from_sites_v2/csvape_images', alt=i['alt'])
                        # these seem to be the same
                        if img:
                            images.append(img)
                    print(f'Downloaded {len(images)}/{len(img_urls)} images for {tag}')


                flavors = extract_options(main, ["flavor", "flavors", "flavor list", "available flavors"])
                colors  = extract_options(main, ["color", "colour", "colors", "available colors", "available colours", "color list", "colour list"])
                nicotine_strengths = extract_options(main, ["nicotine_strength", "nicotine_strengths", "nicotine", "available strengths", "nicotine strengths", "strength", "strengths", "mg", "mg/ml", "mg/ml"])
                bottle_sizes = extract_options(main, ["bottle_size", "bottle_sizes", "size", "sizes", "ml", "oz"])

                # Extract description
                desc = extract_description(main)

                #ingredients 
                ingredients = extract_section_items(main, ["ingredient", "ingredients", ])

                # Package Contents
                package_contents = extract_section_items(main, ["included in the package", "package contents", "in the box", "what's included", "whats included", "contents",  "what's inside", "whats inside",])

                # Key Features
                key_features = extract_section_items(main, ["key features", "features"])

                warnings = extract_section_items(main, ["warnings", "warning", "caution", "safety information"])

                flavor_description = extract_section_items(main, ["flavor description", "flavor profile", "flavor notes", "tasting notes", "flavor details", "flavor description", "flavor profile", "tasting notes", "flavor notes", "flavors", "available_flavors"]) 

                # Extracting product information
                product_data = {
                    'tag': tag,
                    "title": title,
                    "link": full_link,
                    "sale_price": sale_price,
                    "regular_price": reg_price,
                    "image_urls": images, #list
                    'flavor_list': flavors, #list
                    'flavor_text': flavor_description, #str
                    'color_list': colors, #list
                    'nicotine_strengths': nicotine_strengths, #list
                    'bottle_sizes': bottle_sizes, #list
                    "stock_status": '',
                    'site_category': site_section,
                    'images': images,
                    'html': reqtxt,
                    'plain_text': txt,
                    'description': desc,
                    'sku': '',
                    'nicotine_strength': '',
                    'power_level': '',
                    'battery': '',
                    'coil': '',
                    'puffs': '',
                    'eliquid_contents': '',
                    'warnings': warnings,
                    'ingredients': ingredients,
                    'features': key_features,
                    'package_contents': package_contents,
                }

                feats = list()
                #print(desc_fields)
                feat = find_features(desc)
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
                map_product_data(CS_VAPE, product_data)
