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


BASE = 'https://getpop.co' 
company = GETPOP

links = [
    "/disposables/",
    
    # E-Liquids URLs
    "/e-liquids/",
    
    # Pod Systems URLs
    "/pod-systems/",
    "/devices/",
    "/pods/",
    
    # Nicotine Pouches URLs
    "/nicotine-pouches/",
    
    # Shop By Collection URLs
    "/back-in-stock/",
    "/new-arrivals/",
    "/best-sellers/",
    "/flavor-of-the-month",
    "/under-10/",
    "/top-ten/top-ten-bakery/",
    "/top-ten/top-ten-candy/",
    "/top-ten/top-ten-fruity/",
    "/top-ten/top-ten-icy-fruit/",
    "/top-ten/top-ten-mint/",
    "/top-ten/top-ten-tobacco/",
    "/top-ten/top-ten-tropical/",
]

print('TOTAL LINKS', len(links))
found = dict()


def extract_flavor_ratings(soup, class_name='kl_reviews__summary__custom_question--range', split_on=' as an average of '):
    # Find all rating sections
    rating_sections = soup.find_all('div', class_=class_name)

    # Extract data for each rating
    ratings = {}
    for section in rating_sections:
        # Get the flavor/attribute name
        try:
            attribute = section.find('strong').text.strip()
            
            # Get the rating value from the aria-label attribute
            span_elem = section.find('span', attrs={'role': 'img'})
            if span_elem and 'aria-label' in span_elem.attrs:
                aria_label = span_elem['aria-label']
                # Extract the number using string manipulation
                # The format is typically "Reviewers rated X as an average of Y between..."
                parts = aria_label.split(split_on)
                if len(parts) > 1:
                    rating_value = parts[1].split(' ')[0]
                    ratings[attribute] = float(rating_value)
        except Exception as e:
            print(f"Error extracting flavor rating: {e}")
            traceback.print_exc()
            continue
    return ratings


def extract_reviews(soup):

    # Find all review items
    review_items = soup.find_all('div', class_='kl_reviews__review_item')
    if len(review_items) == 0:
        return []
    

    reviews = []
    
    for item in review_items:
        review = {}
        
        # Extract star rating
        stars_container = item.find('div', {'role': 'img'})
        if stars_container:
            aria_label = stars_container.get('aria-label', '')
            star_match = re.search(r'(\d+) star', aria_label)
            if star_match:
                review['rating'] = int(star_match.group(1))
            else:
                review['rating'] = None
        
        # Extract timestamp and convert to actual date
        timestamp_div = item.find('div', class_='kl_reviews__review__timestamp')
        if timestamp_div:
            relative_time = timestamp_div.text.strip()
            actual_date = convert_relative_time_to_date(relative_time)
            review['time'] = relative_time
            review['date'] = actual_date
        
        # Extract title
        title_div = item.find('div', class_='kl_reviews__review__title')
        if title_div and title_div.text.strip():
            review['title'] = title_div.text.strip()
        
        # Extract author name
        author_div = item.find('div', class_='kl_reviews__review__author')
        if author_div:
            name_div = author_div.find('div')
            if name_div:
                review['author'] = name_div.text.strip()
        
        # Check if verified buyer
        verified_span = item.find('span', class_='kl_reviews__review__verified')
        review['verified_buyer'] = bool(verified_span)
        
        # Extract review content
        content_p = item.find('p', class_='kl_reviews__review__content')
        if content_p:
            review['review_text'] = content_p.text.strip()
        
        # Extract variant info
        variant_p = item.find('p', class_='kl_reviews__review__variant')
        if variant_p:
            review['variant'] = variant_p.text.replace('Variant: ', '').strip()
        
        # Extract custom attributes (like Ice Level)
        attributes = {}
        custom_questions = item.find_all('div', class_='kl_reviews__custom_question_answer')
        
        for question in custom_questions:
            question_elem = question.find('strong')
            if question_elem:
                question_text = question_elem.text.strip()
                
                # Handle range-based answers
                if 'range' in question_elem.get('class', []):
                    spans = question.find_all('span')
                    if len(spans) >= 3:  # The range item itself plus the two label spans
                        aria_label = spans[0].get('aria-label', '')
                        value_match = re.search(r'rated .+ as a (\d+)', aria_label)
                        if value_match:
                            value = int(value_match.group(1))
                            attributes[question_text] = value
                else:
                    # Handle text-based answers
                    answer_elem = question.find('span', class_='kl_reviews__custom_question__answer')
                    if answer_elem:
                        attributes[question_text] = answer_elem.text.strip()
        
        if attributes:
            review['attributes'] = attributes
        
        # Extract images if any
        image_row = item.find('div', class_='kl_reviews__review__image_row')
        if image_row and image_row.find_all('img'):
            review['images'] = [img.get('src') for img in image_row.find_all('img')]

        flavor_ratings = extract_flavor_ratings(item, class_name='kl_reviews__custom_question_answer', split_on=' as a ')
        review['iced_level'] = flavor_ratings.get('Ice Level', None)
        review['sweet_level'] = flavor_ratings.get('Sweet Level', None)
        #review['flavor_ratings'] = flavor_ratings
        
        reviews.append(review)
    
    return reviews

def convert_relative_time_to_date(relative_time):
    """Convert relative time (e.g., '29 days ago') to an actual date string."""
    today = datetime.now()
    
    # Match patterns like "X days ago", "X weeks ago", etc.
    days_match = re.search(r'(\d+) days? ago', relative_time)
    weeks_match = re.search(r'(\d+) weeks? ago', relative_time)
    months_match = re.search(r'(\d+) months? ago', relative_time)
    years_match = re.search(r'(\d+) years? ago', relative_time)
    hours_match = re.search(r'(\d+) hours? ago', relative_time)
    minutes_match = re.search(r'(\d+) minutes? ago', relative_time)
    
    if days_match:
        days = int(days_match.group(1))
        date = today - timedelta(days=days)
    elif weeks_match:
        weeks = int(weeks_match.group(1))
        date = today - timedelta(weeks=weeks)
    elif months_match:
        months = int(months_match.group(1))
        # Approximate: a month as 30 days
        date = today - timedelta(days=months*30)
    elif years_match:
        years = int(years_match.group(1))
        # Approximate: a year as 365 days
        date = today - timedelta(days=years*365)
    elif hours_match:
        hours = int(hours_match.group(1))
        date = today - timedelta(hours=hours)
    elif minutes_match:
        minutes = int(minutes_match.group(1))
        date = today - timedelta(minutes=minutes)
    elif "just now" in relative_time.lower():
        date = today
    else:
        # If we can't parse it, return the original text
        return None
    
    return date.strftime('%Y-%m-%d')


def product_attributes(soup):
    script = soup.find("script", string=re.compile(r"var\s+BCData\s*="))
    if not script:
        return {}
    match = re.search(r"var\s+BCData\s*=\s*(\{.*?\});", script.string or "", re.S)
    if not match:
        return {}
    try:
        return json.loads(match.group(1)).get("product_attributes", {})
    except (json.JSONDecodeError, TypeError):
        return {}


def product_identifiers(soup, tag):
    attributes = product_attributes(soup)
    sku = attributes.get("sku")
    unique_id = attributes.get("id") or attributes.get("product_id")
    if not unique_id:
        event_script = soup.find(string=re.compile(r'"product_id"'))
        match = re.search(r'"product_id"\s*:\s*"?(\d+)', event_script or "")
        unique_id = match.group(1) if match else None
    return sku, str(unique_id or "") or None


def product_stock_status(soup):
    attributes = product_attributes(soup)
    if attributes.get("instock") is True:
        return "In Stock"
    if attributes.get("instock") is False:
        return "Out of Stock"
    availability = soup.select_one('meta[property="og:availability"]')
    value = (availability.get("content", "") if availability else "").lower()
    return "In Stock" if value == "instock" else "Out of Stock" if value in {"oos", "outofstock"} else ""

def get_html(url, timeout=120):  # Added timeout parameter


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

        # Robust explicit wait: Wait for multiple elements or a specific element to be visible
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        time.sleep(5) #add a small sleep to ensure any javascript has finished.


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


def main():
    from collections import Counter

    product_list = list()
    all_headers = list()
    header_counter = Counter(all_headers)
    header_samples = dict()
    
    has_header = False
    
    with open(f'scraping/data-latest/{company}_scrape.csv', mode='w') as file:
        page = 1
        homepage = requests.get(BASE, timeout=45)
        discovered = discover_catalog_links(
            homepage.text,
            BASE,
            exclude=("/cart", "/login", "/account", "/compare", "/wishlist", "/search", "/blog", "/pages/"),
        )
        scrape_links = list(dict.fromkeys(links + discovered))
        print(f"Discovered {len(discovered)} Get Pop catalog links; using {len(scrape_links)} total")
        for top_level_link in prioritize_links(scrape_links):
            
            page = 1
            site_section = normalize_site_category(top_level_link)

            while True:
                url = f'{BASE}{top_level_link}?page={page}'
                print(url)

                if url in found:
                    reqtxt = found[url]
                else:
                    simpletxt, reqtxt = get_html(url)
                    found[url] = reqtxt
                #reqtxt = get_html(url)
                soup = BeautifulSoup(reqtxt, features="lxml")
                products = soup.select('article.card, div.product-card')
                print(url, len(products))
                
                if len(products) == 0:
                    break
                page += 1

                for p in products:
                    if not isinstance(p, element.Tag):
                        continue
                    title_node = p.select_one(".card-title, .product-card__title")
                    if not title_node:
                        continue
                    title_ = title_node.get_text(" ", strip=True)
                    brand_node = p.select_one('[data-test-info-type="brandName"], .product-card__vendor')
                    brand_ = brand_node.get_text(" ", strip=True) if brand_node else ""
                    brand_ = brand_.replace('Vendor:', '').strip()

                    brand = None
                    title = f'{brand_} {title_}' 
                    print('TITLE', title)

                    link_node = p.select_one('a.reversed-link[href]') or p.select_one('a[href]')
                    if not link_node:
                        continue
                    link = link_node['href']
                    rpe = p.select_one("[data-product-price-without-tax], .f-price-item")
                    sale_price = None
                    if rpe:
                        reg_price = rpe.text.strip()


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


                    print(link)

                    # if rpe:

                    #     reg_price = rpe.text.strip().replace('Regular price', '')
                    # else:
                    #     reg_price = None

                    full_link = requests.compat.urljoin(BASE, link)

                    img_urls = []

                    tag = link.rstrip('/').split('/')[-1].split('?')[0]

                    if full_link in found:
                        reqtxt = found[full_link]
                    else:
                        # print(full_link)
                        simpletxt, reqtxt = get_html(full_link)
                        found[full_link] = reqtxt
                    print(full_link)
                    psoup = BeautifulSoup(reqtxt, features="lxml")
                    txt = psoup.get_text()
                    sku, unique_id = product_identifiers(psoup, tag)

                    product_id = get_product_id(company, tag)
                    if product_id:
                        print('EXISTS', tag)

                    thumbnails = psoup.select_one('.productView-thumbnails, .product__media-gallery-thumbails')
                    gallery = psoup.select_one('.productView-images, .product__media-gallery-viewer-wrap')
                    img_tags = list()
                    if thumbnails:
                        img_tags.append(thumbnails.find_all('img'))
                    if gallery:
                        img_tags.append(gallery.find_all('img'))

                    for image_list in img_tags:
                        for img_tag in image_list:
                            img_alt = None
                            if img_tag and 'alt' in img_tag.attrs:
                                img_alt = img_tag['alt']

                            if img_tag and 'data-srcset' in img_tag.attrs:
                                spl =  img_tag['data-srcset'].split(',')
                                for s in spl:
                                    if s.strip().startswith('http'):
                                        img_urls.append({'url': s.strip(), 'alt': img_alt})
                                    elif s.strip().startswith('//'):
                                        img_urls.append({'url': 'http:' + s.strip(), 'alt': img_alt})
                            elif img_tag and 'srcset' in img_tag.attrs:
                                spl =  img_tag['srcset'].split(',')
                                for s in spl:
                                    if s.strip().startswith('http'):
                                        img_urls.append({'url': s.strip(), 'alt': img_alt})
                                    elif s.strip().startswith('//'):
                                        img_urls.append({'url': 'http:' + s.strip(), 'alt': img_alt})
                            elif img_tag and 'src' in img_tag.attrs:
                                spl =  img_tag['src'].split(',')
                                for s in spl:
                                    if s.strip().startswith('http'):
                                        img_urls.append({'url': s.strip(), 'alt': img_alt})
                                    elif s.strip().startswith('//'):
                                        img_urls.append({'url': 'http:' + s.strip(), 'alt': img_alt})
                            elif img_tag and 'data-zoom' in img_tag.attrs:
                                # Extract the URL from the data-zoom attribute
                                spl =  img_tag['data-zoom'].split(',')
                                for s in spl:
                                    if s.strip().startswith('http'):
                                        img_urls.append({'url': s.strip(), 'alt': img_alt})
                                    elif s.strip().startswith('//'):
                                        img_urls.append({'url':'http:' + s.strip(), 'alt': img_alt})

                    container = psoup.select_one('.productView-details.product-data, .product__blocks')
                    description_container = psoup.select_one(
                        '.productView-description, .product__blocks'
                    )
                    flavors = []
                    colors = []
                    nicotine_strengths = []
                    bottle_sizes = []
                    product_contents = ''

                    if container:

                        # title = container.find('h1', class_='product__title').text.strip()

            #             # Extract price
            #             price = container.find('span', class_='price price--highlight').text.strip()
            #             compare_price = container.find('span', class_='price price--compare').text.strip()

                        stock_status = product_stock_status(psoup)

                        section_map = dict()
                        description_text = ''
                        # Extract product description
                        highlights_div = container.select_one('.product__block--highlights-block')

                        if highlights_div:
                            summary = highlights_div.find('h2')
                            details = highlights_div.find_all('div', class_='items-center')

                            if summary:
                                description_text += summary.get_text(strip=True)
                            if details:
                                for d in details:
                                    description_text += d.get_text(strip=True)
                                    description_text += '\n'
                            description_text += '\n\n'
                            description_text = description_text.replace('HighlightsHighlights', 'Highlights ')
                        
                        product_blocks = (description_container or container).select(
                            '.product__block--collapsible_tab, details'
                        )
                        if product_blocks:
                            for p in product_blocks:
                                summary = p.find('summary', class_='accordion-details__summary')
                                details = p.find('div', class_='accordion-details__content')

                                is_flavor = False
                                is_contents = False
                                if summary:
                                    sum_text = summary.get_text(strip=True)
                                    print(sum_text)
                                    description_text += sum_text
                                    description_text += '\n'
                                    if 'flavor' in sum_text.lower():
                                        is_flavor = True
                                    if "in the box" in sum_text.lower():
                                        is_contents = True
                                if details:
                                    details_text = details.get_text(strip=True)
                                    lis = details.find_all('li')
                                    if lis and len(lis) > 0:
                                        for l in lis:
                                            description_text += l.get_text(strip=True)
                                            description_text += '\n'

                                            if is_flavor:
                                                flavor = l.get_text(strip=True)
                                                if flavor and flavor not in flavors:
                                                    flavors.append(flavor)
                                            if is_contents:
                                                product_contents += l.get_text(strip=True)
                                                product_contents += '\n'

                                    else:
                                        description_text += details_text
                                    description_text += '\n'
                                description_text += '\n'

                        section_map['description'] = description_text



                    n = 0
                    images = list()
                    for i in img_urls:
                        n += 1
                        images.extend(download_image_batch([i], tag, f'data_from_sites_v2/{company}_images'))
                    print(f'Downloaded {len(images)}/{len(img_urls)} images for {tag}')


                    reviews = extract_reviews(psoup)
                    review_attributes = extract_flavor_ratings(psoup)

                    # Extracting product information
                    product_data = {
                        'tag': tag,
                        "title": title,
                        'reviews': reviews,
                        'review_attributes': review_attributes,
                        'brand': brand,
                        "link": full_link,
                        "sale_price": sale_price,
                        "regular_price": reg_price,
                        "image_urls": images,
                        'flavor_list': flavors,
                        'color_list': colors,
                        'nicotine_strengths': nicotine_strengths,
                        'bottle_sizes': bottle_sizes,
                        "stock_status": stock_status,
                        # Prefer the retailer SKU; fall back to the numeric
                        # BigCommerce product ID, not the site tag.
                        "sku": sku or unique_id or stable_sku(company, tag),
                        'site_category': site_section,
                        'images': images,
                        'html': reqtxt,
                        'plain_text': txt.strip(),
                        'package_contents': product_contents,
                    }
                    desc_fields = ''
                    for s, v in section_map.items():
                        if 'description' not in s:
                            s = s + '_description'
                        product_data[s] = v.replace('\xa0', ' ').strip()
                        if product_data[s] != '':
                            desc_fields += f'\n{product_data[s]}'

                    feats = list()
                    #print(desc_fields)
                    feat = find_features(desc_fields)
                    any_found, puffs_res, nico_res, ml_res, flav_text, dev_text = feat
                    product_data['puffs'] = puffs_res
                    product_data['nicotine_strength'] = nico_res
                    product_data['eliquid_contents'] = ml_res
                    if any_found:
                        #print(feat)
                        feats.append(feat)

                    product_data['battery'] = extract_battery(desc_fields)

                    if product_id:
                        sync_ecig_product_history(product_id, product_data)
                        update_ecig_product_metadata(product_id, sku or unique_id, stock_status)
                        insert_reviews(reviews, product_id)
                        insert_review_attributes(review_attributes, product_id)
                        insert_ecig_price(product_id, reg_price, sale_price)
                    else:
                        map_product_data(company, product_data)

                    #print(product_data)

                    #product_list.append(product_data)

                    #print(product_data.keys())





if __name__ == "__main__":
    
    main()
