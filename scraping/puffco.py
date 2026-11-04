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
import traceback
import json


import json
from datetime import datetime, timedelta

from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from selenium.common.exceptions import NoSuchElementException, TimeoutException




sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from db.db_azure import *
from ecig_parsing import *


BASE = 'https://www.puffco.com' 
company = "PUFFCO"

links = [ '/collections/puffco-collection', '/collections/devices',
         '/pages/proxycollection',
         '/collections/accessories',
         '/collections/consumables',
         '/collections/new-featured',
         '/collections/merch',
]

def get_html(url, timeout=120, clicked=False):  # Added timeout parameter


    driver = None
    html = ''
    simple = ''
    try:
        res = requests.get(url)
        simple = res.text

        options = Options()
        options.add_argument('--headless')
        options.page_load_strategy = 'eager'

        driver = webdriver.Firefox(options=options)
        driver.set_page_load_timeout(timeout)
        driver.get(url)

        if not clicked:
            time.sleep(5)  # Wait for the page to load
            try:
                button = WebDriverWait(driver, 3).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[normalize-space()='Yes']"))
                )
                button.click()
                time.sleep(2)
            except (TimeoutException, NoSuchElementException):
                # The age gate is optional after its cookie is set.
                pass

        driver.maximize_window()
        time.sleep(3)
        
        try: 
            # voyage-close
            button = WebDriverWait(driver, 2).until(
                EC.element_to_be_clickable((By.ID, "voyage-close")))
            # driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});", button  )
                    # If found and clickable, click it
            button.click()

        except (TimeoutException, NoSuchElementException):
            # The optional Voyage promotional dialog may not be present.
            pass


        time.sleep(3)
        

        # Robust explicit wait: Wait for multiple elements or a specific element to be visible
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        time.sleep(1) #add a small sleep to ensure any javascript has finished.
    except Exception as ex:
        print(f"An error occurred: {ex}")
        traceback.print_exc()
        html = simple

    finally:
        if driver:
            html = driver.page_source
            driver.quit()
        else:
            html = simple

    return simple, html

from bs4 import BeautifulSoup
import json

def extract_product_info(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    product_data = {}

    # Extract Basic Info
    title_elem = soup.find('h1')
    if title_elem:
        product_data['title'] = title_elem.get_text(strip=True)

    category_elem = soup.find('p', class_='text-2xs')
    if category_elem:
        product_data['category'] = category_elem.get_text(strip=True)

    # Extract Price
    price_regular = soup.select_one('[data-price-regular]')
    if price_regular:
        # Get the span that doesn't have the 'hidden' class
        price_span = price_regular.find('span', class_=lambda c: not c or 'hidden' not in c)
        if price_span:
            product_data['price'] = price_span.get_text(strip=True)

    # Extract Description
    description_elem = soup.find('div', class_='product__description')
    if description_elem:
        # Use separator to keep paragraph breaks natural
        product_data['description'] = description_elem.get_text(separator=' ', strip=True)

    # Extract Images
    # Targeting the main media gallery images, avoiding thumbnails to prevent duplicates
    product_data['images'] = []
    image_elements = soup.select('.product__media-item.image img')
    for img in image_elements:
        src = img.get('src')
        if src:
            # Clean up URLs that start with '//'
            if src.startswith('//'):
                src = 'https:' + src
            # Avoid adding duplicate image URLs
            if src not in product_data['images']:
                product_data['images'].append(src)

    # Extract Video URLs
    product_data['videos'] = []
    video_sources = soup.select('video source')
    for source in video_sources:
        src = source.get('src')
        if src:
            if src.startswith('//'):
                src = 'https:' + src
            product_data['videos'].append(src)

    # Extract Accordion Details (e.g., What's Included, Warranty, Returns)
    product_data['accordions'] = {}
    accordions = soup.find_all('details')
    for detail in accordions:
        title = detail.find('h2')
        content = detail.find('div', class_='text-2xs')
        if title and content:
            key = title.get_text(strip=True)
            value = content.get_text(separator=' ', strip=True)
            product_data['accordions'][key] = value

    # Extract Variant Data from embedded JSON
    # Product pages often store rich data in application/json script tags
    variant_scripts = soup.select('variant-radios script[type="application/json"]')
    product_data['variants'] = []
    if variant_scripts:
        try:
            for script in variant_scripts:
                variants_json = json.loads(script.string)
                product_data['variants'].extend(variants_json)
        except json.JSONDecodeError:
            pass
            
    # Extract Current Selected Variant Color (if available from the UI)
    selected_color = soup.find(id='selected-variant')
    if selected_color:
         product_data['selected_color'] = selected_color.get_text(strip=True)

    return product_data




def main():
    homepage = requests.get(BASE, timeout=45).text
    discovered = discover_catalog_links(
        homepage,
        BASE,
        prefixes=("/collections/", "/pages/"),
        exclude=("/cart", "/account", "/search", "/blogs/", "/policies/"),
    )
    scrape_links = list(dict.fromkeys(links + discovered))
    print(f"Discovered {len(discovered)} Puffco catalog links; using {len(scrape_links)} total")
    for link in prioritize_links(scrape_links):
        print()
        print('SCRAPING LINK', link)
        print() 

        site_section = normalize_site_category(link)

        url = BASE + link
        page = 1
        while True:
            page_url = f"{url}?page={page}"
            simple, html = get_html(page_url)
            soup = BeautifulSoup(html, 'html.parser')

            # Add your parsing logic here to extract product information from the soup object
            # For example, you can find product names, prices, descriptions, etc.

            # Example of extracting product names (this will depend on the actual HTML structure of the page)
            products = soup.select('div.product-card, .product-card-wrapper, [data-product-card]')
            
            if not products or len(products) == 0:
                break  # If no products found, break the loop

            page += 1  # Move to the next page

            for product in products:
                print(product.text.strip())  # Print or store the product name

                prod_url = product.get('data-url')
                if not prod_url:
                    link = product.select_one('a[href*="/products/"]')
                    prod_url = link.get('href') if link else None
                if not prod_url:
                    continue
                tag = prod_url.split('/')[-1].split('?')[0]

                prod_link = f'{BASE}{prod_url}'

                simpletxt, reqtxt = get_html(prod_link)

                print(prod_link)
                psoup = BeautifulSoup(reqtxt, features="lxml")
                txt = psoup.get_text()
                product_info = extract_product_info(reqtxt)

                title = product_info.get('title') or tag.replace('-', ' ').title()
                data = {
                    "title": title,
                    "link": prod_link,
                    "site_category": site_section,
                    "tag": tag,
                    "html": reqtxt,
                    "plain_text": txt,
                    "regular_price": product_info.get('price', ''),
                    "sale_price": "",
                    "flavor_text": "",
                    "description": product_info.get('description', ''),
                    "package_contents": "",
                    "features": "",
                    "ingredients": "",
                    "warnings": "",
                    "eliquid_contents": "",
                    "puffs": "",
                    "coil": "",
                    "battery": "",
                    "power_level": "",
                    "nicotine_strength": "",
                    "stock_status": '',
                    "reviews": extract_reviews(psoup),
                    "review_attributes": {},
                    "flavor_list": [],
                    "nicotine_strengths": [],
                    "images": [],
                }

                product_id = get_product_id(company, tag)
                if product_id:
                    print('EXISTS', tag)
                    sync_ecig_product_history(product_id, data)
                    update_ecig_product_metadata(product_id, stable_sku(company, tag))
                    print(f"REVIEWS {tag}: {len(data['reviews'])} found" if data['reviews'] else f"REVIEWS {tag}: none found")
                    if data['reviews']:
                        insert_reviews(data['reviews'], product_id)
                    continue

                n = 0
                images = list()
                for i in product_info.get('images', []):
                    n += 1
                    images.extend(download_image_batch([{'url': i, 'alt': title}], tag, f'data_from_sites_v2/{company}_images'))
                print(f'Downloaded {len(images)}/{n} images for {tag}')
                data['images'] = images
                print(f"REVIEWS {tag}: {len(data['reviews'])} found" if data["reviews"] else f"REVIEWS {tag}: none found")
                map_product_data(company, data)

if __name__ == "__main__":  
    main()
