
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

from selenium.common.exceptions import TimeoutException

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


BASE = 'https://vapesourcing.com' 
company = VAPE_SOURCING

links = [
    # Disposables
      '/disposable-vapes.html',
    "/cotton-candy-disposable-vape.html",
    "/fruit-flavor-disposable-vape.html",
    "/dessert-flavor-disposable-vape.html",
    "/tobacco-flavor-disposable-vape.html",
    "/watermelon-ice-disposable-vape.html",
    "/ice-vapes.html",
    "/clear-flavor-vapes.html",
    "/sour-flavor-disposable-vapes.html"
    '/ice-vapes.html', '/sour-flavor-disposable-vapes.html',
    '/cotton-candy-disposable-vape.html', '/tobacco-flavor-disposable-vape.html',
    '/clear-flavor-vapes.html', '/fruit-flavor-disposable-vape.html', '/dessert-flavor-disposable-vape.html',
    '/rechargeable-disposable.html',
      '/disposable-vape-with-screen.html', '/low-nicotine-vape.html',
    '/nicotine-free-vape.html', '/multi-use-disposable-vape.html', '/smart-phone-disposable-vapes.html',
    '/flavor-control-vapes.html', '/disposable-hookah.html', '/disposables-bundle.html',
    '/disposable-vape-with-double-tanks.html', '/disposable-vape-with-detachable-battery.html',
    '/disposables-under-10.html', '/clearance-disposables.html',
    '/ploox.html', '/ploox.html', '/ploox.html', '/raz.html', '/raz.html',
    '/geek-bar.html', '/geek-bar.html', '/lost-mary.html', '/lost-mary.html', '/flum.html', '/flum.html',
    '/nexa.html', '/nexa.html', '/olit.html', '/foger.html', '/mr-fog.html', '/kado-bar.html',
    '/adjust-vape.html', '/fume-vape.html', '/vozol.html', '/off-stamp-vape.html',
    'oxbar-astro-maze-50k.html', 'nexa-pix-35k.html', 'lost-angel-mate-50k.html', 'flum-ut-bar-50000.html',
    '/60000-puffs.html', '/50000-puffs.html', '/40000-puffs.html', '/30000-puffs.html',
    '/25000-puffs.html', '/20000-puffs.html', '/15000-puffs.html', '/10000-puffs.html',

    # E-liquids
    '/e-juice.html', '/fruits-flavor-e-juice.html', '/sweet-flavor-e-juice.html',
    '/menthol-flavor-e-juice.html', '/tobacco-flavor-e-juice.html', '/salt-nic.html',
    '/0-mg-e-juice.html', '/20-60-mg-e-juice.html', '/3-12-mg-e-juice.html',
    'naked-100-euro-gold-e-juice-60ml.html', 'naked-100-tobacco-american-patriot-e-juice-60ml.html',
    'tropic-mango-ice-urban-tale-e-juice-30ml.html',

    # Brands
    '/brand.html',  '/smok.html', '/uwell.html', '/geek-vape.html', '/joyetech.html',
    '/voopoo.html', '/vaporesso.html', '/eleaf.html', '/lost-vape.html', '/hellvape.html',
    '/vandy-vape.html', '/innokin.html', '/ijoy.html', '/freemax.html', '/naked-100.html',
    '/pod-juice.html', '/i-love-salts.html', '/blvk-unicorn.html', '/juice-head.html',
    '/twist-salt.html', '/finest.html', '/vapetasia.html', '/candy-king.html', '/coastal-clouds.html',
    '/skwezed.html', '/cloud-nurdz.html', '/pachamama.html', '/vape-7-daze.html', '/innevape.html',
    '/hi-drip.html', '/jam-monster.html', '/sadboy.html', '/mad-hatter.html',

    # Other Specific Categories
    # Vape Kits
    '/starter-kit.html', '/refillable-vape.html', '/boro-kit.html', '/pod-system-kit.html',
    '/mod-pod-kits.html', '/vape-mod-kits.html', '/vape-pen-kits.html', 'geekvape-aegis-hero-5-kit.html',
    'uwell-caliburn-g4-pro-kit.html', 'geekvape-aegis-legend-5-kit.html', 'uwell-caliburn-g4-kit.html',

    # Mods
    '/battery-device.html', '/box-mod.html', '/mechanical-mods.html', '/dna-vape-mod.html',
    '/squonk-mod.html', '/built-in-battery-mods.html', '/boro-mod.html', '/high-end-mods.html',
    'timesvape-the-dreamer-clutch-mod.html', 'vandy-vape-pulse-aio-v2-kit.html',
    'voopoo-drag-5-box-mod.html', 'lost-vape-centaurus-bt200-box-mod.html',

    # Tanks
    '/atomizer-tank.html', '/rda.html', '/rta.html', '/rdta.html', '/boro-tank.html',
    '/sub-ohm-tank.html', '/mesh-tank.html', '/mouth-to-lung-tank.html', '/replacement-pod-and-cartridge.html',
    'thunderhead-creations-blaze-max-rta.html', 'hellvape-fat-rabbit-solo-2-rta.html',
    'hellvape-dead-rabbit-3-rta-joker-edition.html', 'vaporesso-xros-series-corex-3-pod-cartridge.html',

    # Accessories
    '/accessories.html', '/nicotine-pouches.html', '/nicotine-strips.html', '/nicotine-gum.html',
    '/batterycell.html', '/replacement-glass-tube.html', '/replacement-coils-heads.html',
    '/charger.html', '/wire-wick-tool.html', '/drip-tip.html', '/other-accessories.html',
    'zyn.html', 'g-pulse-nicotine-pouches.html', 'lucy.html', 'melta.html', 'slapple-nicotine-gum.html',
    'mates-brand-pouchmate-nicotine-pouches.html',

    # Vaporizers
    '/vaporizers.html', '/yocan.html', '/doteco.html', '/ccell.html', '/lookah.html',
    '/hamilton-devices.html', '/puffco.html', '/ltq-vapor.html', '/wax.html', '/dry-herb.html',
    '/510-thread-battery.html', '/vapor-cup.html', '/bongs-water-pipes.html', '/dab-rig.html',
    'the-kind-pen-bullet-2-vaporizer.html', 'yocan-deuce-510-thread-battery.html',
    'iecigbest-tobor-electric-dab-rig.html', 'ploox-nest-portable-hookah.html',

    # Uncategorized / Promotions / Misc
    '/clearance.html', '/mystery-box.html', '/buy-one-get-one.html',
    '/crazy-sale.html', '/multi-buy.html', '/best-vape.html', '/coupons.html',  '/featured.html',
]

print('TOTAL LINKS', len(links))
found = dict()

def get_html(url, clicked=False, closed=True, elements=True, load_more=False):

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

        # wait = WebDriverWait(driver, 10) 
        # wait.until(EC.visibility_of_element_located((By.CLASS_NAME, "modal-content")))

        if not clicked:
            button = driver.find_element(By.CLASS_NAME, "age-yes")
            button.click()

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
                print("Button clicked.")
            except TimeoutException:
                print("Button not found or not clickable.")

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
        print(ex)
        html = ''
    finally:
        if driver:
            driver.close()
    time.sleep(3)


    return html

def get_reviews(psoup):
    reviews = []
    rsoup = psoup.find('div', class_='reviews-content')
                
    if rsoup:
        review_items = rsoup.find_all('div', class_='reviews-item')
        for review in review_items:

            
            # Reviewer name and date

            name = review.find('div', class_='name').find('p').text.strip()
            date = review.find('span', class_='date').get_text(strip=True) if review.find('span', class_='date') else ''
            if date == '':
                date = review.find('div', class_='date').get_text(strip=True) if review.find('div', class_='date') else ''

            # Rating (percentage or stars)
            rating_style = review.find('div', class_='rating')['style']
            rating_percent = rating_style.split(':')[-1].strip('; %')
            rating_stars = round(int(rating_percent) / 20)

            # Review text
            review_text = review.find('div', class_='detail').text.strip()

            # Review images
            image_tags = review.select('div.reviews-img img')
            image_urls = [img.get('src', img.get('data-src')) for img in image_tags]

            # Recommendation and ease of use
            paragraphs = review.find_all('p')
            recommendation = ""
            ease_of_use = ""
            for p in paragraphs:
                if "Recommendation Status" in p.text:
                    recommendation = p.text.split(":")[-1].strip()
                elif "Easy Of Use" in p.text:
                    ease_of_use = p.text.split(":")[-1].strip() 

            reviews.append({
                "date": date,
                "author": name,
                "review_text": review_text,
                "stars": rating_stars,
                'image_url': image_urls[0] if image_urls else '',
            })
    return reviews

if __name__ == "__main__":
    from collections import Counter

    product_list = list()
    all_headers = list()
    header_counter = Counter(all_headers)
    header_samples = dict()
    
    has_header = False
    
    homepage = requests.get(BASE, timeout=45)
    discovered = discover_catalog_links(
        homepage.text,
        BASE,
        prefixes=("/",),
        exclude=("/cart", "/checkout", "/customer", "/catalogsearch", "/blog", "/author", "/review"),
    )
    scrape_links = list(dict.fromkeys(links + discovered))
    print(f"Discovered {len(discovered)} VapeSourcing catalog links; using {len(scrape_links)} total")
    for top_level_link in prioritize_links(scrape_links):
        if not top_level_link.startswith('/'):
            continue
        page = 1
        site_section = normalize_site_category(top_level_link)


        while True:
            url = f'{BASE}{top_level_link}?page={page}'
            print(url)


            if url in found:
                reqtxt = found[url]
            else:
                reqtxt = get_html(url)
                found[url] = reqtxt
            #reqtxt = get_html(url)
            soup = BeautifulSoup(reqtxt, features="lxml")
            products = soup.find_all('li', class_='product-item')
            print(url, len(products))

            
            page_div = soup.find('div', class_='page')
            max_page = int(page_div['data-total']) if page_div and 'data-total' in page_div.attrs else None

            if not max_page:
                max_page = 25
            if page > max_page:
                break

            page += 1

            for p in products:
                # Extracting product information
                product_name_elem = p.select_one('.product-name a')
                if not product_name_elem:
                    continue
                product_name = product_name_elem.get_text(strip=True).replace('Clearance', '').replace('Pre-order', '')
                img_soup = p.select_one('.product-image img')
                if img_soup:
                    image_url = img_soup.get('src', img_soup.get('data-src', ''))
                else:
                    image_url = ''
                
                product_link = p.select_one('.product-name a')
                product_url = product_link['href']

                full_link = product_url if product_url.startswith('http') else BASE + product_url
                tag = product_url.split('/')[-1].replace('.html', '').strip()  
                
                price_obj = p.select_one('.special-price .price')
                if price_obj:
                    price = price_obj.get_text(strip=True)
                else:
                    price = ''


                if full_link in found:
                    preqtxt = found[full_link]
                else:
                    preqtxt = get_html(full_link)
                    found[full_link] = preqtxt
                #reqtxt = get_html(url)
                psoup = BeautifulSoup(preqtxt, features="lxml")

                product_id = get_product_id(company, tag)
                if product_id:
                    print('EXISTS', tag, '; checking product history, price history, and images')

                product_main = psoup.find('div', class_='product-main')
                osoup = psoup.find('div', class_='product-options')


                product_options = {}

                for option in psoup.select('.options-list'):
                    label = option.select_one('.info-title').get_text(strip=True).replace('*', '').replace(':', '')
                    items = [li.get_text(strip=True) for li in option.select('ul li')]
                    product_options[label] = items

                flavor_list = product_options.get('Flavors', product_options.get('Flavor', []))
                colors = product_options.get('Colors', product_options.get('Color', []))

                product_detail_main = psoup.find('div', class_='product-detail-main')

                if product_detail_main:
                    # Brand, Unit, Type, Net Weight
                    details = product_detail_main.select('ul.top li')
                    if details and len(details) > 0:
                        if details[0].find('b'):
                            brand = details[0].find('b').text.strip()
                        else:
                            brand = details[0].get_text().replace('Brand:', '').strip()
                    else:
                        brand = ''

                    # Introduction
                    title_div = product_detail_main.find('div', class_='title')
                    if title_div:
                        intro_title = title_div.text.strip()
                        intro_paragraphs = [p.text.strip() for p in product_detail_main.find_all('p') if p.text.strip()]
                    else:
                        intro_title = ''
                        intro_paragraphs = ''

                    # Features
                    features = [p.text.strip('• ') for p in product_detail_main.find_all('p') if '•' in p.text]

                    # Pros and Cons
                    uls =  product_detail_main.find_all('ul')
                    if len(uls) > 3:
                        pros = [li.text.strip() for li in uls[3].find_all('li')]
                    else:
                        pros = []
                    if len(uls) > 4:
                        cons = [li.text.strip() for li in product_detail_main.find_all('ul')[4].find_all('li')]
                    else:
                        cons = []

                    # Package list
                    package_list = [p.text.strip() for p in product_detail_main.find_all('div', class_='title') if 'PACKAGE LIST' in p.text]
                    package_items = [p.text.strip() for p in product_detail_main.find_all('p') if 'Pyne Pod Boost' in p.text or 'Flavor Gift Box' in p.text]
                    package_contents = package_list + package_items

                    # Images
                    images = [img['src'] for img in product_detail_main.find_all('img') if 'pyne_pod' in img['src']]
                    if image_url != '':
                        images.append(image_url)



                    # Ordering tips
                    tips = product_detail_main.find('p', class_='normal_tips')
                    if tips:
                        ordering_tip = tips.text.strip()
                    else:
                        ordering_tip = ''

                    faqs = psoup.find('div', class_='faqs-list')
                    if faqs:
                        faq_text = faqs.get_text(separator='\n').strip() 
                    else:
                        faq_text = ''

                    description = f"{intro_title}\n" + "\n".join(intro_paragraphs) + "\n\n" + \
                                "Features:\n" + "\n".join(features) + "\n\n" + \
                                "Pros:\n" + "\n".join(pros) + "\n\n" + \
                                "Cons:\n" + "\n".join(cons) + "\n\n" + \
                                "Package Contents:\n" + "\n".join(package_contents) + "\n\n" + \
                                f"Ordering Tip:\n{ordering_tip}" + "\n\n" + \
                                f"FAQs:\n{faq_text}"
                else:
                    description = ''
                    faq_text = ''
                    ordering_tip = ''
                    images = []
                    if image_url != '':
                        images.append(image_url)
                    package_contents = []
                    features = []
                    brand = ''
                
                valid_image_list = []
                img_n = 0
                should_download_images = not product_id or not product_has_images(product_id)
                if should_download_images:
                    for i in images:
                        img_n += 1
                        img_path = f'{tag}_{img_n}'
                        valid_image_list.extend(download_image_batch([{'url': i, 'alt': product_name}], img_path, f'data_from_sites_v2/{company}_images'))
                    print(f'Downloaded {len(valid_image_list)}/{img_n} images for {tag}')
                else:
                    print(f"IMAGES EXIST for product_id {product_id}; skipping image download")

                reviews = get_reviews(psoup)
                
                
                product_data = {
                    'tag': tag,
                    "title": product_name,
                    "brand": brand,
                    "link": full_link,
                    "sale_price": '',
                    "regular_price": price,
                    'flavor_list': flavor_list, #list
                    'flavor_text': '', #str
                    'color_list': colors, #list
                    'nicotine_strengths': '', #list
                    'bottle_sizes': '', #list
                    "stock_status": '',
                    'site_category': site_section,
                    'images': valid_image_list,
                    'html': preqtxt,
                    'plain_text': psoup.get_text(separator='\n'),
                    'description': description,
                    'sku': '',
                    'nicotine_strength': '',
                    'power_level': '',
                    'battery': '',
                    'coil': '',
                    'puffs': '',
                    'eliquid_contents': '',
                    'warnings': '',
                    'ingredients': '',
                    'features': '\n'.join(features),
                    'package_contents': '\n'.join(package_contents),
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
                    if valid_image_list:
                        insert_product_images(product_id, valid_image_list)
                    insert_reviews(reviews, product_id)
                    insert_ecig_price(product_id, price, None)
                else:
                    print('MAP PRODUCT DATA', product_name, top_level_link)
                    map_product_data(VAPE_SOURCING, product_data)
