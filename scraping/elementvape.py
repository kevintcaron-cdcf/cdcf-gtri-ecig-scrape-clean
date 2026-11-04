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
from urllib.parse import unquote



import json
from datetime import datetime, timedelta

from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from selenium.common.exceptions import TimeoutException, NoSuchElementException




sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from db.db_azure import *
from ecig_parsing import *


BASE = 'https://www.elementvape.com' 
company = ELEMENT_VAPE
CHALLENGE_WAIT_SECONDS = 300

links = [
    '/disposable',
    "/50k-puff-disposables",
    "/nicotine-free-vape",
    "/best-disposables",
    "/disposables-bogo",
    "/usa-disposable-vapes",
    "/delta-8-disposables",
    "/tobacco-vape",
    '/disposables-bundle',
    '/nixodine-disposables',
    '/clearance-disposables',

    

    "/fruit-flavors-e-liquid",
    "/dessert-flavors-e-liquid",
   
    "/tobacco-e-liquid",
    '/nicotine-salt-e-liquid',
    '/unflavored-e-liquid',
    '/clearance-200',
    '/official-retailer',
     "/menthol-e-liquid",
    '/e-liquids',


    "/starter-kits",
    "/pod-systems",
    "/box-mod-kits",
    "/vape-pen-kits",
    "/clearance-starter-kits",
    "/box-mods",
    


    "/hemp-disposables",
    "/hemp-cartridges",
    "/delta-8",
    "/thc-p",
    "/hhc",
    "/thca",
    "/hemp-pre-rolls",
    "/hemp-edibles",
        "/hemp",

    "/vaporizers",
    "/510-battery",
    "/electric-dab-rigs",
    "/dry-herb-vaporizers",
    "/concentrate-vaporizers",
    "/pen-vaporizers",
    "/desktop-vaporizers",
    "/vaporizers-accessories",
    "/nicotine-pouches",
    "/mint-nicotine-pouches",
    "/fruit-nicotine-pouches",
    "/unflavored-nicotine-pouches",
    "/coffee-nicotine-pouches",
    "/nicotine-strips",
    "/nicotine-gum",
    "/glass",
    "/bongs",
    "/bubblers",
    "/dab-rigs",
    "/glass-hand-pipes",
    "/glass-accessories",
    "/grinders",
    "/rolling-papers",
    "/cigars",
    "/cigar-boxes",
    "/Cigarillos",
    "/cigar-accessories",
    "/cigar-samplers",
    "/cigar-5-packs",
    "/accessories",
    "/vape-coils",
    "/replacement-pod-cartridges",
    "/rebuildable-materials",
    "/nicotine-pouches",
    "/vaporizers-accessories",
    "/glass-accessories",
    "/new-arrivals",

    "7-daze-e-liquids",
    "aaok",
    "alp",
    "anml-e-liquids",
    "arro",
    "avct-avictor-tech",
    "adjust",
    "advken-technology",
    "air-factory-e-liquid",
    "airfuze",
    "airis",
    "airmez",
    "al-fakher",
    "aleader",
    "aleaf",
    "alec-bradley",
    "aloha-sun",
    "alt-zero",
    "arizer",
    "arturo-fuente",
    "aspire",
    "astral-project",
    "astro-eight",
    "auxo",
    "asmodus-distribution",
    "bd-vape",
    "blnkr",
    "blurrbar",
    "blvk-unicorn",
    "boutiq",
    "bp-mods",
    "bad-drip-labs",
    "badger-hill",
    "bam-bam-s-cannoli",
    "bar-juice",
    "barista-brew-co",
    "baton-vapor",
    "bear-quartz",
    "beard-vape-co-e-liquid",
    "beri",
    "big-bottle-co",
    "binoid",
    "blank-bar",
    "blazy-susan",
    "blitz-enterprises",
    "bomb-vape",
    "boulder",
    "boundless",
    "cao-cigars",
    "cbdfx",
    "ccell",
    "chlz-nicotine-pouches",
    "clew",
    "crazyace",
    "crft-cultivation",
    "cabin-crew",
    "cake-brand",
    "cali-extrax",
    "candy-king-ejuice",
    "carats",
    "cartisan",
    "cassadaga-liquids",
    "chapo-extrax",
    "charlies-chalk-dust-e-liquid",
    "cheech",
    "cheech-chongs",
    "chill-steel-pipes-brand",
    "chillax",
    "chubby-gorilla",
    "chubby-vapes",
    "cloud-nurdz-e-liquid",
    "cloud-v",
    "cloudious9",
    "coastal-clouds-co",
    "cohiba",
    "coil-master",
    "cookies",
    "country-clouds",
    "craving-vapor",
    "crispy-blunts",
    "crossing-tech",
    "cutleaf",
    "cuttwood-e-liquids",
    "cyrine",
    "czar",
    "d8flight",
    "dazzvape",
    "dkhaan",
    "dogg-lbs",
    "dojo",
    "dovpo-technology",
    "dozo",
    "driiizy",
    "dynavap",
    "davinci-vaporizers",
    "damn-vape",
    "davidoff",
    "daywalker",
    "dazzleaf",
    "death-row",
    "delta-extrax",
    "delta-munchies",
    "diesel",
    "dimension-12",
    "dimo-hemp",
    "doctor-big-vapes",
    "dome-wrecker",
    "dope-boyz",
    "dotmod",
    "dr-dabber",
    "drew-estate",
    "drink-delta",
    "dripmore",
    "efx",
    "elf-thc",
    "elux",
    "ep-carrillo",
    "eyce",
    "efest",
    "eighty-six",
    "eleaf",
    "eb",
    "empire-glassworks",
    "equator",
    "exodus",
    "fasta-vapes",
    "flaka",
    "flum",
    "fryd-e-liquid",
    "fume-vape",
    "fumi",
    "fuyl",
    "fvkd",
    "feed-sync",
    "fifty-bar",
    "fire-department",
    "firerose",
    "five-pawns-eliquids",
    "flying-monkey",
    "focus-v",
    "foger-technology",
    "formula-420",
    "four-seasons",
    "freemax",
    "fresh-farms",
    "frozen-fields",
    "fruitia",
    "grav-labs",
    "grdnt",
    "galaxy-treats",
    "geek-thc-x",
    "geek-vape",
    "geekd-extracts",
    "geekfuze",
    "ghost-hemp",
    "bsx-vapor",
    "glob-mops",
    "good-extracts",
    "good-girls-only",
    "gorilla-warfare",
    "grenco-science",
    "gurkha",
    "gost-vapor",
    "h-upmann",
    "honcho",
    "hqd-technology",
    "half-bakd",
    "hamilton-devices",
    "hazy-mary",
    "hellvape",
    "hemper",
    "hi-drip",
    "hixotic",
    "hidden-hills",
    "hideseek",
    "hohm-tech-inc",
    "honeyroot-wellness",
    "honeystick",
    "horizon-tech",
    "hugo-vapor",
    "human-grade",
    "humble-juice-eliquid",
    "huni-badger",
    "hyde",
    "ion",
    "ispire",
    "iykyk",
    "innevape",
    "innokin",
    "ijoy",
    "jnr",
    "jus-vape",
    "juul",
    "jimmy-the-juice-man",
    "joyetech",
    "juice-head-e-liquid",
    "juice-king",
    "juice-roll-upz-e-liquid",
    "juicy-kush",
    "keko",
    "kilo-e-liquids",
    "kori",
    "kros",
    "kyk",
    "kangertech",
    "kangvape",
    "keep-it-100-e-liquid",
    "king-palm",
    "kream",
    "kumi",
    "kynn-labs",
    "litto",
    "lucid",
    "luffbar",
    "luxx",
    "lve",
    "la-gloria-cubana",
    "leaf-buddi",
    "lemonnade",
    "lil-baby",
    "limitless-mod-co",
    "liquid-assets",
    "little-high",
    "litty",
    "logic",
    "lolo",
    "lookah",
    "looper",
    "los-statos",
    "losgal",
    "lost-angel",
    "lost-mary",
    "lost-thc",
    "lost-vape",
    "lucy",
    "lume",
    "mechvape",
    "melta",
    "mfu",
    "mj-arsenal",
    "mnke-bars",
    "mrkt",
    "mtrx",
    "macanudo",
    "mad-hatter",
    "mellow-fellow",
    "memers",
    "memory-lane",
    "merica-bar-vape",
    "met4-vapors-e-liquids",
    "metaku",
    "mighty-vapors",
    "mints-vape",
    "mmelt",
    "modern-herb-co",
    "modus",
    "jam-monster-liquids",
    "montecristo",
    "mr-fog",
    "mr-freeze-e-liquid",
    "mucho",
    "muha-meds",
    "my-father",
    "mycan",
    "myvapors",
    "nexa",
    "niq",
    "nice-leaf",
    "njoy",
    "nwtn",
    "naked-100-e-liquid",
    "nasty-juice",
    "neu",
    "neuro",
    "nicci",
    "nitecore",
    "nitros-cold-brew",
    "nomenon",
    "north-vapes",
    "nose-knows",
    "nowadays",
    "obs-technology",
    "oeo",
    "olit",
    "on-nicotine-pouches",
    "one-vape",
    "orgnx-eliquids",
    "oxbar",
    "oxva",
    "ocho-extracts",
    "odyssey",
    "off-stamp",
    "one-hit-wonder-e-liquids",
    "one-up-vapor",
    "ooze",
    "orca-vape",
    "oumier",
    "pax-labs",
    "pica-bar",
    "plugplay",
    "puro-cannagars",
    "pachamama-cbd",
    "phantoms-cannabliss",
    "phix",
    "pillow-talk",
    "pillowz",
    "pioneer4you-ipv",
    "plasencia",
    "ply-rock",
    "pod-juice-e-liquid",
    "poseidon-artifacts",
    "pressure-la",
    "prima",
    "prohibition-juice-co",
    "propaganda-e-liquids",
    "puffco",
    "puffshot",
    "pulsar-vaporizers",
    "punch-cigars",
    "purlyf",
    "purple",
    "pushing-ps",
    "pynepod",
    "pyro",
    "qit",
    "rama",
    "raw",
    "raz",
    "relx-vape",
    "rogue",
    "roos",
    "runtz",
    "ryot",
    "randys",
    "releafy",
    "rick-flair-drip",
    "rincoe",
    "ripe-vapes-e-liquids",
    "road-trip",
    "rocky-patel",
    "romeo-y-julieta",
    "ruthless",
    "sadboy-e-liquid",
    "saveurvape",
    "sbx",
    "sea",
    "skwezed-e-liquid",
    "smoktech",
    "soc",
    "sofi",
    "stiiizy",
    "stnr",
    "storz-bickel",
    "strio",
    "svrf-e-liquid",
    "swft",
    "salt-bae-50",
    "samsung",
    "santa-cruz",
    "sense-technology",
    "sesh",
    "seshgear",
    "shijin-vapor",
    "sigelei",
    "silverback-juice",
    "slam-juice",
    "slapple",
    "sluggers",
    "smoant",
    "smoke-fiends",
    "smoking-vapor",
    "smookah",
    "smyle-labs",
    "snoopy-smoke",
    "snowwolf",
    "so-soul",
    "solaris",
    "sony",
    "sorbet-pop",
    "sour-house",
    "south-disposables",
    "space-gods",
    "spaceman",
    "stache",
    "steam-crave",
    "stratus-smoke",
    "stundenglass",
    "suicide-bunny",
    "suicide-mods",
    "suorin",
    "tre-house",
    "teslacigs-tesla-vape",
    "the-finest-e-liquid",
    "the-hemp-doctor",
    "the-kind-pen",
    "the-mamasan",
    "think-vape-technology",
    "thundercloud",
    "thunderhead-creations",
    "tinted-brew-liquid-co",
    "torch",
    "traditions-juice-co",
    "trinity-hemp",
    "tronian",
    "true-story",
    "truweigh",
    "tsunami-premium",
    "twist-e-liquid",
    "tyson",
    "upends",
    "urb",
    "ut-bar",
    "ultroner",
    "utillian",
    "uwell",
    "v-syndicate",
    "vapengin",
    "vapmod",
    "veepon",
    "velo",
    "vfeel",
    "vgod",
    "viho",
    "vlab",
    "vnm",
    "vozol",
    "vpr-brands",
    "vuse",
    "vandy-vape",
    "vape-breakfast-classics",
    "vape-dinner-lady",
    "vapefly",
    "vaperz-cloud",
    "vapetasia",
    "vaporesso",
    "vaptio",
    "vessel",
    "viva-la-hemp",
    "vladdin-vapor",
    "voopoo-tech",
    "whatabar",
    "white-label",
    "white-rhino",
    "wismec",
    "wotofo",
    "wyn",
    "wynn",
    "x-posed",
    "xqs",
    "xtra",
    "xvape",
    "yibla",
    "yll-vape",
    "yocan",
    "yovo",
    "yihi-sxmini",
    "yogi-e-liquids",
    "ud-youde-technology",
    "zimo",
    "zone",
    "zyn",
    "zen-haus",
    "zeus-rsenal",
    "zig-zag",
    "zombi"
]

print('TOTAL LINKS', len(links))
found = dict()


def infite_scroll(driver):

    last_height = driver.execute_script('return document.body.scrollHeight')
    while True:
        driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
        time.sleep(2)
        new_height = driver.execute_script('return document.body.scrollHeight')
        if new_height == last_height:
            break
        last_height = new_height

def get_driver(headless=True, timeout=120):
    options = Options()
    if headless:
        options.add_argument('--headless')
    options.page_load_strategy = 'eager'

    driver = webdriver.Firefox(options=options)
    driver.set_page_load_timeout(timeout)
    return driver


def element_vape_blocked(html):
    text = BeautifulSoup(html or '', 'lxml').get_text(' ', strip=True).lower()
    return any(marker in text for marker in (
        'verify you are human',
        'access denied',
        'just a moment',
        'security check',
        'checking your browser',
        'captcha',
    ))


def wait_for_element_vape_challenge(driver, url, timeout=CHALLENGE_WAIT_SECONDS):
    if not driver or not element_vape_blocked(driver.page_source):
        return
    sys.stdout.write('\a')
    sys.stdout.flush()
    print(
        f'Element Vape challenge detected for {url}. Complete it in the '
        f'visible browser; waiting up to {timeout}s.'
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not element_vape_blocked(driver.page_source):
            print('Element Vape challenge cleared')
            return
        time.sleep(2)
    raise RuntimeError(f'Element Vape challenge did not clear: {url}')


def get_html(url, timeout=120, init_time=60, clicked=False, load_more=False, driver=None, headless=True):  # Added timeout parameter

    html = ''
    simple = ''
    try:
        res = requests.get(url)
        simple = res.text

        if not driver:
            options = Options()
            if headless:
                options.add_argument('--headless')
            options.page_load_strategy = 'eager'

            driver = webdriver.Firefox(options=options)
            driver.set_page_load_timeout(timeout)
        driver.get(url)
        wait_for_element_vape_challenge(driver, url)



        if not clicked:
            time.sleep(init_time)  # Wait for the page to load
            try:
                button = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable(
                        (By.XPATH, "//button[contains(translate(., 'YES', 'yes'), 'yes')]")
                    )
                )
                button.click()
                time.sleep(1)
            except (TimeoutException, NoSuchElementException):
                # The age gate is cookie-backed and may already be cleared.
                pass

        driver.maximize_window()


        infite_scroll(driver)

        load_n = 0
        if load_more:
            while True:
                try:
                    # Wait up to a short time for the element to be clickable (e.g., 2 seconds)
                    # This acts as the loop mechanism
                    button = WebDriverWait(driver, 2).until(
                        EC.element_to_be_clickable((By.XPATH, "//button[text()='Load More']")))
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});", button  )

                    time.sleep(3)
                    # If found and clickable, click it
                    button.click()
                    load_n += 1
                    print(f"Button clicked, load count: {load_n}. Checking for next occurrence...")

                    infite_scroll(driver)

                except (TimeoutException, NoSuchElementException):
                    # If the element is not visible/present within the time, stop the loop
                    print("Button not visible or found. Stopping loop.")
                    break
                except Exception as e:
                    # Handle other potential exceptions
                    print(f"An unexpected error occurred: {e}")
                    break
                    time.sleep(3) #add a small sleep to ensure any javascript has finished.
        else:
            time.sleep(3)  # Wait for any additional content to load after scrolling


    except Exception as ex:
        print(f"An error occurred: {ex}")
        traceback.print_exc()
        html = simple

    finally:
        if driver:
            html = driver.page_source
            
        else:
            html = simple

    return simple, html

def extract_from_product_page(soup):

    # Extract product data
    product_data = {
        'product_name': '',
        'price': '',
        'stock_status': '',
        'rating': '',
        'review_count': '',
        'images': [],
        'description': '',
        'short_description': '',
        'features': {},
        'available_flavors': [],
        'reviews': []
    }

    # Product Name
    product_name_elem = soup.find('h1', {'id': 'gallery-next-area'})
    if product_name_elem:
        product_data['product_name'] = product_name_elem.get_text(strip=True)

    # Price
    price = soup.find(string=re.compile(r'\$\s*\d+\.\d+'))
    if price:
        # print(price.strip())  # Output: $ 24.99
        
        # Convert to float
        price_value = float(re.search(r'(\d+\.\d+)', price).group(1))
        product_data['price'] = price_value

    # Stock Status
    stock_elem = soup.find('p', class_='text-[#207338]')
    if stock_elem:
        product_data['stock_status'] = stock_elem.get_text(strip=True)

    # Rating and Review Count
    rating_elem = soup.find('div', class_='yotpo-bottom-line-score')
    if rating_elem:
        product_data['rating'] = rating_elem.get_text(strip=True)

    # Product Images
    image_slider = soup.find('div', class_='image-swiper-slide')
    if image_slider:
        image_elems = image_slider.find_all('img')
        if image_elems:
            for image_elem in image_elems:
                src = image_elem.get('src', '')
                alt = image_elem.get('alt', '')
                if src and 'placeholder' not in src and 'svg' not in src and 'headless-logo' not in src and not src.startswith('data:image'):
                    product_data['images'].append({
                        'url': src,
                        'alt': alt
                    })

    # Short Description
    short_desc_elem = soup.find('div', class_='shortDescription-links')
    if short_desc_elem:
        product_data['short_description'] = short_desc_elem.get_text(strip=True)

    # Full Description
    description_elem = soup.find('div', class_='pdp-description')
    if description_elem:
        product_data['description'] = description_elem.get_text(strip=True)

    # Features
    features_section = soup.find('p', {'id': 'HWG23YA'})
    if features_section:
        features_text = features_section.get_text(strip=True)
        product_data['features'] = {
            'raw_features': features_text
        }

    # Available Flavors
    flavor_select = soup.find('select', {'id': 'Flavors'})
    if not flavor_select:
        flavor_select = soup.find('select', {'id': 'Flavor'})
    if flavor_select:
        for option in flavor_select.find_all('option'):
            flavor = option.get_text(strip=True)
            if flavor and 'select' not in flavor.lower() and 'choose' not in flavor.lower():
                # is_available = 'out of stock' not in flavor.lower()
                product_data['available_flavors'].append(flavor)

    # Reviews
    reviews_list = soup.find_all('div', class_='yotpo-review')
    for review in reviews_list:
        review_data = {}
        
        # Reviewer name
        reviewer_name = review.find('span', class_='yotpo-reviewer-name')
        if reviewer_name:
            review_data['author'] = reviewer_name.get_text(strip=True)
        
        # Review title
        review_title = review.find('div', class_='yotpo-review-title')
        if review_title:
            review_data['title'] = review_title.get_text(strip=True)
        else:
            review_data['title'] = ''
        
        # Review content
        review_content = review.find('div', class_='yotpo-read-more-text')
        if review_content:
            review_data['content'] = review_content.get_text(strip=True)
        else:
            review_data['content'] = ''

        if review_data['title'] == review_data['content'] and review_data['title'] != '' and review_data['content'] != '':
            review_data['review_text'] = review_data['title'] 
        else:
            review_data['review_text'] = review_data['title'] + ': ' + review_data['content']
        
        # Review date
        review_date = review.find('div', class_='yotpo-date-format')
        if review_date:
            review_data['date'] = review_date.get_text(strip=True)
        
        # Review rating (count stars)
        stars = review.find_all('svg', class_='yotpo-sr-star-full')
        review_data['rating'] = len(stars)
        
        # Verified buyer status
        verified = review.find('span', class_='yotpo-reviewer-verified-buyer-text')
        review_data['verified_buyer'] = verified is not None
        
        # Recommendation status
        recommendation = review.find('div', class_='yotpo-custom-questions-value')
        if recommendation:
            review_data['recommendation'] = recommendation.get_text(strip=True)
        
        # Helpfulness votes
        vote_elements = review.find_all('div', class_='yotpo-review-votes-number')
        if len(vote_elements) >= 2:
            review_data['helpful_votes'] = vote_elements[0].get_text(strip=True)
            review_data['not_helpful_votes'] = vote_elements[1].get_text(strip=True)
        
        if review_data:
            product_data['reviews'].append(review_data)

    return product_data

def extract_from_product(soup):
    product_data = {}


    # 2. Extract image URL and alt text
    img_tags = soup.find_all('img')
    for img in img_tags:
        alt_text = img.get('alt', '')
        src = img.get('src', '')
        
        # Skip placeholder images (data:image/svg+xml or empty alt)
        if 'data:image' not in src and 'svg' not in src and alt_text and alt_text.strip():
            product_data['image_alt'] = alt_text
            
            # Extract the actual image URL from the src attribute
            if 'url=' in src:
                # Parse the URL parameter from Next.js image optimization
                url_match = re.search(r'url=([^&]+)', src)
                if 'placeholder' in src or 'headless-logo' in src:    
                    url_match = None
                if url_match:
                    encoded_url = url_match.group(1)
                    product_data['image_url'] = unquote(encoded_url)
            else:
                product_data['image_url'] = src
            
            # Extract srcset for different resolutions
            srcset = img.get('srcset', '')
            if srcset:
                product_data['image_srcset'] = srcset
            
            break  # Take the first valid product image

    # 3. Extract product name and URL
    product_link = soup.find('a', class_=lambda x: x and 'text-skin-base' in x)
    if product_link:
        product_data['name'] = product_link.text.strip()
        product_data['url'] = product_link.get('href', '')

    # 4. Extract price
    price_tag = soup.find('p', class_=lambda x: x and 'font-semibold' in x and 'text-skin-base' in x)
    if price_tag:
        price_text = price_tag.text.strip()
        # Remove any extra text after the price
        product_data['price'] = price_text.split()[0] if price_text else None

    return product_data

def main():
    from collections import Counter

    product_list = list()
    all_headers = list()
    header_counter = Counter(all_headers)
    header_samples = dict()
    
    has_header = False

    driver = get_driver(headless=False, timeout=120)
    
    with open(f'scraping/data-latest/{company}_scrape.csv', mode='w') as file:
        homepage = requests.get(BASE, timeout=45)
        discovered = discover_catalog_links(
            homepage.text,
            BASE,
            prefixes=("/",),
            exclude=("/cart", "/login", "/account", "/search", "/blog", "/pages/", "/contact"),
        )
        scrape_links = list(dict.fromkeys(links + discovered))
        print(f"Discovered {len(discovered)} Element Vape catalog links; using {len(scrape_links)} total")
        for top_level_link in prioritize_links(scrape_links):

            print()
            print('SCRAPING LINK', top_level_link)
            print()
            
            site_section = normalize_site_category(top_level_link)

            if not top_level_link.startswith('/'):
                top_level_link = '/' + top_level_link


            url = f'{BASE}{top_level_link}'
            print(url)

            if url in found:
                reqtxt = found[url]
            else:
                simpletxt, reqtxt = get_html(url, load_more=True, driver=driver)
                found[url] = reqtxt
            #reqtxt = get_html(url)
            soup = BeautifulSoup(reqtxt, features="lxml")
            products = soup.select(
                'div.plp-product-list, .product-card, [data-product-card], '
                'a.product-item-link, a[href*="/products/"]'
            )
            print(url, len(products))
            
            if len(products) == 0:
                break


            for p in products:
                if not isinstance(p, element.Tag):
                    continue
   
                product_data = extract_from_product(p)
                product_url = product_data.get('url', '')
                if product_url and not product_url.startswith('http'):
                    product_data['url'] = BASE + product_url
                product_tag = product_url.split('/')[-1] if product_url else 'unknown'
                if product_tag == 'unknown':
                    print("Warning: Product URL is missing or invalid.")
                    continue

                product_id = get_product_id(company, product_tag)
                exists = False
                if product_id:
                    print(top_level_link, 'EXISTS', product_tag)
                    update_ecig_product_metadata(product_id, stable_sku(company, product_tag))
                    exists = True
                else:                    
                    print(top_level_link, 'NEW', product_tag)
                purl = product_data['url']
                print(purl)

                if purl in found:
                    preqtxt = found[purl]
                else:
                    psimple_text, preqtxt = get_html(purl, load_more=False, driver=driver)
                    found[purl] = preqtxt

                psoup = BeautifulSoup(preqtxt, features="lxml")
                detailed_product_data = extract_from_product_page(psoup)
                regular_price = detailed_product_data.get('price', '')

                if not exists:
                    images = list()
                    img_urls = detailed_product_data.get('images', [])
                    main_image = {}
                    if 'image_url' in product_data and product_data['image_url'] != '':
                        main_image = {
                            'url': product_data['image_url'],
                            'alt': product_data.get('image_alt', '')
                        }   
                        img_urls.append(main_image)
                    n = 0
                    for i in img_urls:
                        if i and i.get('url', '').strip() == '':
                            continue
                        n += 1
                        images.extend(download_image_batch([i], product_tag, f'data_from_sites_v2/{company}_images'))
                    print(f'Downloaded {len(images)}/{len(img_urls)} images for {product_tag}')
                

                    data = {
                        "title": product_data.get('name', ''),
                        "link": product_data.get('url', ''), 
                        "site_category": site_section,
                        "tag": product_tag,
                        "html": preqtxt,
                        "plain_text": psoup.get_text(strip=True),
                        "regular_price": regular_price,
                        "sale_price": "",
                        "flavor_text": "",
                        "description": detailed_product_data['description'],
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
                        "stock_status": detailed_product_data.get('stock_status', ''),
                        "reviews": detailed_product_data.get('reviews', []),
                        "flavor_list": detailed_product_data.get('available_flavors', []),
                        "nicotine_strengths": [],
                        "images": images
                    }

                    feat = find_features(detailed_product_data.get('description', ' '))
                    any_found, puffs_res, nico_res, ml_res, flav_text, dev_text = feat
                    data['puffs'] = puffs_res
                    data['nicotine_strength'] = nico_res
                    data['eliquid_contents'] = ml_res
                    data['battery'] = extract_battery(detailed_product_data.get('description', ' '))
                    try:
                        print(f"{top_level_link} --Mapping product data for {product_tag}...")
                        map_product_data(company, data)
                    except Exception as e:
                        print(f"{top_level_link} --Error mapping product data for {product_tag}: {e}")
                        traceback.print_exc()
                else:
                    print(f"{top_level_link} -- Product {product_tag} already exists in the database. Skipping insertion.")
                    # update reviews

                    history_data = {
                        "title": product_data.get("name", ""),
                        "site_category": site_section,
                        "description": detailed_product_data.get("description", ""),
                        "puffs": "",
                        "nicotine_strength": "",
                        "eliquid_contents": "",
                        "battery": "",
                        "stock_status": detailed_product_data.get("stock_status", ""),
                    }
                    any_found, puffs, nicotine, liquid, _, _ = find_features(history_data["description"])
                    history_data.update({"puffs": puffs, "nicotine_strength": nicotine, "eliquid_contents": liquid, "battery": extract_battery(history_data["description"])})
                    sync_ecig_product_history(product_id, history_data)

                    insert_ecig_price(product_id, regular_price, None)

                    reviews = detailed_product_data.get('reviews', [])
                    if reviews and len(reviews) > 0:
                        try:
                            print(f"Updating reviews for existing product {product_tag} with {len(reviews)} reviews.")
                            insert_reviews(reviews, product_id)
                        except Exception as e:
                            print(f"An error occurred while updating reviews for product {product_tag}: {e}")
                            traceback.print_exc()
    if driver:
        driver.quit()



if __name__ == "__main__":
    
    main()
