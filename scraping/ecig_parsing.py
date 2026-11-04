# import spacy
# import en_core_web_sm
# nlp = en_core_web_sm.load()

import requests
import re
import json
from bs4 import BeautifulSoup
import time
import csv
import pandas as pd
from collections import Counter

from PIL import Image
try:
    import pillow_avif  # noqa: F401  # Registers AVIF support with Pillow.
except ImportError:
    pillow_avif = None
from io import BytesIO
import os
from urllib.parse import urljoin, urlsplit, urlunsplit
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv(os.path.join(os.getcwd(), ".env"))


def prioritize_links(links):
    """Order category URLs from highest to lowest project priority."""
    def priority(link):
        value = urlsplit(link).path.lower().replace("-", " ").replace("_", " ")
        if any(term in value for term in ("new arrival", "newest", "new product", "new release", "new vapes")):
            return -1
        if any(term in value for term in ("thc", "delta 8", "delta 9", "delta 10")):
            return 4
        if any(term in value for term in ("disposable", "disposables", "puff", "nixodine")):
            return 0
        if any(term in value for term in (
            "pod", "closed refill", "replacement cartridge", "cartridge", "prefilled",
            "refillable vape", "pod system", "nicotine salt",
        )):
            return 1
        if any(term in value for term in (
            "e liquid", "eliquid", "e juice", "ejuice", "vape juice", "salt nic",
        )):
            return 2
        return 3

    return [link for _, link in sorted(enumerate(links), key=lambda item: (priority(item[1]), item[0]))]


def extract_reviews(soup):
    """Extract common JSON-LD and review-widget markup into the DB contract."""
    reviews, seen = [], set()

    def date_value(value):
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date().isoformat() if value else None
        except (TypeError, ValueError):
            return None

    def add(author, body, rating=None, date=None, verified=False, variant=None):
        body = (body or "").strip()
        if not body:
            return
        try:
            rating = float(rating) if rating not in (None, "") else None
        except (TypeError, ValueError):
            rating = None
        item = {"date": date_value(date), "author": (author or "").strip() or None,
                "rating": rating, "verified_buyer": bool(verified),
                "review_text": body, "variant": (variant or "").strip() or None}
        key = (item["author"], item["review_text"], item["date"])
        if key not in seen:
            seen.add(key)
            reviews.append(item)

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            values = json.loads(script.string or script.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        values = values if isinstance(values, list) else [values]
        for product in values:
            if not isinstance(product, dict):
                continue
            product_reviews = product.get("review", [])
            product_reviews = product_reviews if isinstance(product_reviews, list) else [product_reviews]
            for review in product_reviews:
                if not isinstance(review, dict):
                    continue
                author = review.get("author", {})
                rating = review.get("reviewRating", {})
                add(author.get("name") if isinstance(author, dict) else author,
                    review.get("reviewBody"), rating.get("ratingValue") if isinstance(rating, dict) else rating,
                    review.get("datePublished"))

    for item in soup.select(".jdgm-rev[data-review-id], .yotpo-review, .reviews-item, .review-item, [data-review-id]"):
        rating_node = item.select_one("[data-score], [data-rating], [data-review-rating], [aria-label*='star']")
        rating = None
        if rating_node:
            rating = rating_node.get("data-score") or rating_node.get("data-rating") or rating_node.get("data-review-rating") or rating_node.get("aria-label")
            match = re.search(r"\d+(?:\.\d+)?", str(rating)) if rating else None
            rating = match.group(0) if match else None
        author = item.select_one(".jdgm-rev__author, .yotpo-user-name, .review-author, .author, [data-review-author]")
        body = item.select_one(".jdgm-rev__body, .yotpo-review-content, .review-text, .review-body, .detail, [data-review-text]")
        date = item.select_one(".jdgm-rev__timestamp, .yotpo-review-date, .review-date, time, [data-review-date]")
        variant = item.select_one(".jdgm-rev__prod-info, .review-variant, [data-review-variant]")
        add(author.get_text(" ", strip=True) if author else None,
            body.get_text(" ", strip=True) if body else None, rating,
            (date.get("datetime") or date.get("data-review-date") or date.get_text(" ", strip=True)) if date else None,
            item.get("data-verified-buyer") == "true" or bool(item.select_one(".verified, .verified-buyer")),
            variant.get_text(" ", strip=True) if variant else None)
    return reviews


def normalize_site_category(value):
    """Return a readable category without URL prefixes, slashes, or suffixes."""
    category = (value or "").split("?", 1)[0].strip("/")
    category = re.sub(r"^https?:--(?:www\.)?[^-]+-", "", category, flags=re.I)
    category = re.sub(r"^https?--(?:www\.)?[^-]+-", "", category, flags=re.I)
    category = re.sub(r"^collections-", "", category, flags=re.I)
    category = re.sub(r"^https?://", "", category, flags=re.I)
    category = re.sub(r"^(?:www\.)?[^/]+/", "", category, flags=re.I) if "://" not in category and "." in category.split("/", 1)[0] else category
    for prefix in ("collections/", "product-category/", "category/", "brand/", "pages/"):
        if category.lower().startswith(prefix):
            category = category[len(prefix):]
            break
    category = category.replace("/", "-").replace("_", " ")
    category = re.sub(r"\.html?$", "", category, flags=re.I)
    return re.sub(r"\s+", " ", category).strip(" /-")


def discover_catalog_links(html, base, prefixes=(), exclude=()):
    """Extract and deduplicate internal catalog links from navigation HTML."""
    soup = BeautifulSoup(html or "", "lxml")
    found = []
    seen = set()
    excluded = tuple(value.lower() for value in exclude)
    for link in soup.select("nav a[href], header a[href], .navPages a[href], a[href]"):
        href = link.get("href", "").strip()
        absolute = urljoin(base, href)
        parts = urlsplit(absolute)
        path = parts.path.rstrip("/")
        lower = path.lower()
        if not path or parts.netloc.lower() != urlsplit(base).netloc.lower():
            continue
        if any(value in lower for value in excluded):
            continue
        if "/products/" in lower or "/product/" in lower:
            continue
        if prefixes and not any(lower.startswith(prefix.lower()) for prefix in prefixes):
            continue
        canonical = urlunsplit((parts.scheme, parts.netloc, path, "", ""))
        if canonical not in seen:
            seen.add(canonical)
            found.append(path)
    return found

section_strings_raw = {
    'Display Screen': 'screen',
    'Charging': 'charging',
    'Operation': 'operation',
    'Prefilled Capacity': 'prefilled',
    'Compatibility': 'compatibility',
    'Ingredients': 'ingredients',
    'INCLUDES': 'package_contents',
    "What's Included": 'package_contents',
    'Package Content': 'package_contents',
    'Package Contents': 'package_contents',
    'Package Includes': 'package_contents',
    'Included in package': 'package_contents',
    'Included in the Package': 'package_contents',
    'Included': 'package_contents',
    'Includes': 'package_contents',
    "What’s Included": 'package_contents',
    'CALIFORNIA PROPOSITION 65 - Warning': 'warning',
    'Warning': 'warning',
    'AVAILABLE OPTIONS': 'key_features',
    'Key Features': 'key_features',
    'Features': 'key_features',
    'Flavors': 'flavors',
    'Flavor Selection': 'flavors',
    'Flavor Options': 'flavors',
    'Cutting-Edge Design and Technology:': 'key_features',
    'Superior Versatility and Performance:': 'key_features',
    'Flavor Selection:': 'flavors',
    'WARNING': 'warning',
    'Description': 'description',
    'Product Specifications': 'specifications',
    'Available Flavors': 'flavors',
    'Flavor Profiles': 'flavors',
    'Exceptional Flexibility and Performance': 'performance',
    'Disposable': 'disposable',
    'Lost Mary x Elf Bar OS5000 Disposable Features': 'key_features',
    'Tailored to Your Preference': 'preference',
    'Why Geek Bar Skyview Disposable?': 'why',
    'Enjoy My Shisha on the Go': 'enjoyment',
    'The Ultimate Vaping Experience': 'enjoyment',
    'Elevate Your Vaping Experience': 'enjoyment',
    'Why Choose the Juice Head 30K Disposable?': 'why',
    'Why Geek Bar Skyview Disposable?': 'why',
    'Hotbox Features': 'key_features',
    'Lost Mary x Elf Bar OS5000 Disposable Features': 'key_features',
    'Experience the Ultimate Vaping Innovation': 'innovation',
    'Flavor Details': 'flavors',
    'Advanced Dual Mesh Coil': 'coil',
    'Coil Specifications': 'coil',
    'Puff Count': 'puffs',
    'Max Puffs': 'puffs',
    'Nicotine Strength': 'nicotine',
    'Battery Capacity': 'battery',
    'E-liquid Capacity': 'e_liquid',
    'Maximum Puffs': 'puffs',
    'Available Flavor Profiles': 'flavors',
    'Prefilled': 'prefilled',
    'Compatible Devices': 'devices',
    'Devices': 'devices',
    'California Proposition 65 Warning': 'warning',
    'Melli Flavors': 'flavors',
    'Airflow': 'airflow',
    'Heating Element': 'heating_element',
    'Digital Screen': 'screen',
    "FAQ's": "faqs",
    "FAQs": "faqs",
    "FAQ": "faqs",
    'LED Screen': 'screen',
    'Display Screen': 'screen',
    'Charging': 'charging',
    'Charging Port Info': 'charging',
    'Operation': 'operation',
    'Prefilled Capacity': 'prefilled',
    'Compatibility': 'compatibility',
    'Compatible with': 'compatibility',
    'Ingredients': 'ingredients',
    'INCLUDES': 'package_contents',
    'Kit Includes': 'package_contents',
    "What's Included": 'package_contents',
    'Package Content': 'package_contents',
    'Package Contents': 'package_contents',
    'Package Includes': 'package_contents',
    'Included in package': 'package_contents',
    'Included in the Package': 'package_contents',
    'Included': 'package_contents',
    'Includes': 'package_contents',
    'Contents': 'package_contents',
    "What’s Included": 'package_contents',
    'CALIFORNIA PROPOSITION 65 - Warning': 'warning',
    'CAUTION: this Product Contains Nicotine. Nicotine is an addictive chemical.': 'warning',
    'Warning': 'warning',
    'AVAILABLE OPTIONS': 'key_features',
    'Features and Specifications': 'key_features',
    'Key Features': 'key_features',
    'Features': 'key_features',
    'Flavors': 'flavors',
    'Flavor Selection': 'flavors',
    'Flavor Options': 'flavors',
    'Cutting-Edge Design and Technology:': 'key_features',
    'Superior Versatility and Performance:': 'key_features',
    'Flavor Selection:': 'flavors',
    'WARNING': 'warning',
    'Description': 'description',
    'Product Specifications': 'specifications',
    'Specifications': 'specifications',
    'Available Flavors': 'flavors',
    'Flavor Profiles': 'flavors',
    'Exceptional Flexibility and Performance': 'performance',
    'Disposable': 'disposable',
    'Lost Mary x Elf Bar OS5000 Disposable Features': 'key_features',
    'Tailored to Your Preference': 'preference',
    'Why Geek Bar Skyview Disposable?': 'why',
    'Enjoy My Shisha on the Go': 'enjoyment',
    'The Ultimate Vaping Experience': 'enjoyment',
    'Elevate Your Vaping Experience': 'enjoyment',
    'Why Choose the Juice Head 30K Disposable?': 'why',
    'Why Geek Bar Skyview Disposable?': 'why',
    'Features and Specifications': 'key_features',
    'Hotbox Features': 'key_features',
    'Lost Mary x Elf Bar OS5000 Disposable Features': 'key_features',
    'Experience the Ultimate Vaping Innovation': 'innovation',
    'Flavor Details': 'flavors',
    'Advanced Dual Mesh Coil': 'coil',
    'Coil Specifications': 'coil',
    'Battery Info': 'battery',
    'Battery': 'battery',
    'Puffs per Device': 'puffs',
    'Puff Count': 'puffs',
    'Max Puffs': 'puffs',
    'What Is a Puff Count?': 'puffs',
    'Nicotine Strengths': 'nicotine',
    'Nicotine Level': 'nicotine',
    'Available Nicotine': 'nicotine',
    'Nicotine': 'nicotine',
    'Nicotine Strength': 'nicotine',
    'Battery Capacity': 'battery',
    'E-liquid Capacity': 'e_liquid',
    'E-liquid contents': 'e_liquid',
    'E-Liquid contents': 'e_liquid',
    'Maximum Puffs': 'puffs',
    'Available Flavor Profiles': 'flavors',
    'Prefilled': 'prefilled',
    'Compatible Devices': 'devices',
    'Devices': 'devices',
    'California Proposition 65 Warning': 'warning',
    'Melli Flavors': 'flavors',
    'Airflow': 'airflow',
    'Adjustable Airflow': 'airflow',
    'Heating Element': 'heating_element',
    'Quick Links': 'links',
    'Quick Link': 'links',
    'Related Links':'links',
    'Related Link':'links',
    'Colors': 'colors',
    'Color': 'colors',
    'Available Colors': 'colors',
    'Quick links': 'links',
    'Flavor': 'flavors',
    'Size': 'size',
    'Sizes': 'size',
    'Dimensions': 'size',
    'Bottle Size': 'size',
    'Bottle Sizes': 'size',
    'Return and Exchange Policy Disclaimer:': 'returns',
    'Returns': 'returns',
    'Pods': 'pods',
    'Pod Info': 'pods',
    'Pod Capacity': 'pods',
    'Options': 'options',
    'Option': 'options',
    'Compatible Hardware': 'hardware',
    'Hardware': 'hardware',
    'Wattage Info': 'wattage',
    'Wattage': 'wattage',
    'Coil': 'coil',
    'Coils': 'coil',
    'Available Nicotine': 'nicotine',
    'How Are Disposables Different Than Others?': 'disposable',
    'VG/PG Ratio': 'vgpg_ratio',
    'VGPG Ratio': 'vgpg_ratio',
    'VG-PG Ratio': 'vgpg_ratio',
    'Vg/Pg Ratio': 'vgpg_ratio',
    'Power Mode Settings': 'power_mode',
    'Power Mode': 'power_mode',
    '3D Curved Screen': 'screen',
    'Name Change': 'name',
    'Variable Wattage': 'wattage',
    'Disposable Vape Battery': 'battery',
    'Battery Pack/Charging Dock': 'battery'

}

brands = ['7 Daze Reds Apple Salt',
 'Lucy Pouches',
 'Pod Juice x Hyde IQ 5000',
 'North 5000 ZERO',
 'Air Bar AB10000',
 'ORGNX 4000',
 'SVL BX12000',
 'HQD Cuvie Bar 7000',
 'Elf Bar BC5000',
 'Kado Bar x Pod King PK5000',
 'Hyde N-Bar Mini 2500',
 '7 Daze Ohmlet 7000',
 'Puff Plus',
 'Oxbar Magic Maze 2',
 'Pop HIT FLEX 3000',
 'Geek Bar Skyview 25K',
 'Air Bar ATRON 5000',
 'Fire ZERO 5000',
 'DigiFlavor x Geek Bar Lush 20K',
 'Space Mary SM8000',
 'Friobar DB7000',
 'VGOD Pod 1K',
 '7 Daze Egge 3000',
 'Pop HIT Solo 5500',
 'Lost Mary MO20000 PRO',
 'Block 6000',
 'UWELL',
 'Pod Juice Salt',
 'VGOD Pod 4K-R',
 'Pod Mesh FLO',
 'Air Bar AB5000',
 'HQD Cuvie Plus',
 'Pop Hit Salt',
 'Lost Mary OS5000 ZERO',
 'Pop HIT Bar 4000 ZERO',
 'Rama 16000',
 'Fume Pouches',
 'HandShake 15K Pod',
 'Hyppe Max Flow',
 'Puff Max 5000',
 'Bidi Stick 500',
 'Flum Pebble 6000',
 'Flum Float 3000',
 'Tyson 2.0 Round 2',
 'Monster Bars 3500',
 'Pop HIT Extra 3000 TFN',
 'Esco Bars Mesh 2500',
 'Hyde Edge RAVE Recharge',
 'Fume Ultra 2500',
 'Foodgod Zero',
 'VGOD Pod 1500',
 'Geek Bar Meloso Max 9000',
 'Kado Bar Vintage Edition 20K',
 'EB Create BC5000 Thermal Edition',
 'Mintopia 6000',
 'STIG',
 'Pod 5500',
 'VGOD SaltNic',
 'Esco Bars Mesh 6000',
 'Kado Bar BR5000',
 'Hyppe Max Air 5000',
 'Custard Monster Salt',
 'Geek Bar Pulse 15000',
 'STIG XL',
 'Kado Bar Pouches',
 'Squid 1.6K',
 'HQD Cuvie Air 4000',
 'Elf Bar ZERO BC5000',
 'Geek Bar B5000',
 'Fume Infinity 3500',
 'Jam Monster Salt',
 'Geek Bar Pulse X 25K',
 'The Milk Salt',
 'RAZ TN9000',
 'RabBeats RC10000 Touch',
 'Rare Mega 5000 Mesh',
 'Mr Fog Switch SW15000',
 'Air Bar Diamond 500',
 'Pod Pocket 7500',
 'Hyde X 3000',
 'Hyde N-Bar Recharge',
 'Tyson 2.0 Heavy Weight 7000',
 'Elux Cyberover 18000',
 'Geek Bar Meloso Mini 1500',
 'Air Bar Mini 2000',
 'Lost Vape Lightrise TB 18K',
 'Modus x Kado Bar KB10000',
 'Hyde x Pod Juice Salt',
 'Frozen Fruit Monster Salt',
 'Elf Bar BC5000 Ultra',
 'Pop HIT Bar 4000',
 'Lost Vape Orion Bar 10000',
 'Hyde Rebel Pro 5000',
 'Lost Mary BM5000',
 'Rare Bar 6000 Mesh',
 'Fume Extra',
 'RAZ CA6000',
 'SMOK Novo Bar AL6000',
 'Lost Mary OS5000',
 'Bliss Bar 5000',
 'Rare Palm 10000',
 'Lost Mary MT15000 Turbo',
 'Fruit Monster Salt',
 'Air Bar Diamond Box 20000',
 'TWIST 6000',
 'EB Design BC5000',
 'Air Bar Box 3000 by NKD100',
 'Air Bar Nex 6500',
 'Lost Vape Orion Bar 7500',
 'Puff Flow',
 'Air Bar Lux',
 'Flum GIO 3000',
 'Elf Bar x Pod King XC5000',
 'Air Bar Box 3000',
 'Oxbar Magic Maze Pro 10K',
 'Mintopia Turbo 9000',
 'Monster Bars Max 6000',
 'Strio x EB Create XC6500',
 'Elf Bar Airo Max 5000',
 'Pod 2500',
 'Kado Bar KB10000',
 'Hyde Edge Recharge',
 'EB Design TE6000',
 'Lost Mary OS5000 4%',
 'ORGNX Salt',
 'ZYN',
 'Lost Mary MO5000',
 'SMOK Spaceman Prism 20K',
 'Pop Pro',
 'Lucy Breakers',
 'North 5000 3%',
 'HQD Cuvie Plus 2.0',
 'PacksPod 5000',
 'North FT12000',
 'Hyde IQ Recharge',
 'QIT',
 'Hyde Retro RAVE Recharge',
 'Funky Republic Ti7000',
 'RAZ DC25000',
 'Fog X Box 6000',
 'Fume Eternity 20000',
 'Fume Unlimited 7000',
 'Fume Infinity Plus 4500',
 'Fifty Bar 6500']

brand_str = '''Juul
Hyde
Esco
Hyppe
Air Bar
Fume
Pod Juice
Lost Mary
Elf Bar
Kado Bar
Foodgood Zero
Monster Bars
Squid
Geek Bar
SMOK
Vuse
Blu
Njoy
MarkTen
Logic
Vapour2
Halo
Apollo
South Beach Smoke
Smok
Vaporesso
Innokin
Aspire
Eleaf
Joyetech
Geekvape
Uwell
Freemax
Vandy Vape
Wotofo
Lost Vape
Dovpo
Hellvape
Oumier
Augvape
Rincoe
OBS
Kangertech
Sigelei
iJoy
HQD
Foodgod
Pop
Flum
7 Daze
Teslacigs
EHPRO
Voopoo
Rincoe
Think Vape
iPV
Vapefly
Squid Industries
Purge Mods
The Vape Lounge
SvoëMesto
Revenant Vape
SnowWolf
Vaperz Cloud
Vicious Ant
ORGNX
Rare Mega
Rig Mod
Block
Rare Bar
Kennedy Vapor
Purge Ally
Deathwish Modz'''

brand_list = brand_str.split('\n')
brand_list.extend(brands)
brand_list = list(set(brands))

flavors = '''Chocolate
Vanilla
Strawberry
Blueberry
Raspberry
Cherry
Lemon
Lime
Orange
Grape
Watermelon
Apple
Pineapple
Mango
Peach
Apricot
Banana
Coconut
Caramel
Toffee
Butter
Peanut butter
Almond
Hazelnut
Pistachio
Mint
Peppermint
Spearmint
Cinnamon
Licorice
Anise
Root beer
Cola
Bubblegum
Cotton candy
Maple
Honey
Ginger
Espresso
Cappuccino
Irish cream
Rum
iced tea
Whiskey
Champagne
Red wine
White wine
Margarita
Pina colada
Mojito
Bloody Mary
Blue raspberry
Sour apple
Sour cherry
Sour lemon
Sour lime
Sour orange
Sour grape
Sour watermelon
Sour strawberry
Sour blueberry
Blackberry
Boysenberry
Cranberry
Elderberry
marshmallow
marshmallows
churro
churros
Kiwi
Passion fruit
Guava
Lychee
punch
Fig
Plum
Papaya
Black currant
Raspberry lemonade
Strawberry kiwi
Orange creamsicle
Key lime pie
Pomegranate
milk
Blueberry cheesecake
Peach cobbler
Apple pie
Pecan pie
melon
candy
cake
tropical
berry
cookie
lemonade
fruit punch
Mint chocolate chip
Chocolate fudge
Brownie batter
Cookies and cream
Rocky road
Snickerdoodle
ice cream
cola
menthol
Tiramisu
Chocolate truffle
Red velvet cake
Carrot cake
Lemon meringue pie
Grapefruit
Limeade
Pineapple upside down cake
Chocolate covered strawberry
Mint julep
Eggnog
berries
bubble gum
lemonade
Hot chocolate
Pumpkin spice
donut
gummy bear
snow cone
sno cone
fruit
fruity
tutti frutti
tutti-frutti
cinnamon
raspberry
blueberry
Margarita
Piña Colada
Daiquiri
coffee
soda
espresso
Mojito
Bloody Mary
Moscow Mule
Manhattan
Martini
Cosmopolitan
Long Island Iced Tea
Sex on the Beach
Mai Tai
Whiskey Sour
Tom Collins
Gin and Tonic
White Russian
Black Russian
butterscotch
Harvey Wallbanger
Tequila Sunrise
Paloma
Sangria
Mimosa
Bellini
Aperol Spritz
Negroni
Sazerac
Blue Hawaiian
Irish Coffee
Hot Toddy
Kamikaze
Lemon Drop Martini
Apple Martini
Espresso Martini
Chocolate Martini
Mojito Martini
Dirty Martini
espresso
lemon drop
Boulevardier
Salted caramel'''

words = '|'.join(list(set(flavors.split('\n'))))
flavor_regex = re.compile('({})'.format(words), flags=re.IGNORECASE)

def extract_options(soup, header_name):
    options = []
    header = soup.find('span', text=header_name)
    if header:
        # Find the next div with the class 'block-swatch-list' containing the options
        option_div = header.find_next('div', class_='block-swatch-list')
        if option_div:
            inputs = option_div.find_all('input', class_='block-swatch__radio')
            for option in inputs:
                options.append(option['value'])
    return options

def extract_salt_nic_val_and_unit(input_string):
    """
    Parses strings like "50mg (5%)" and returns a list of tuples.
    """
    matches = re.findall(r'(\d+(?:\.\d+)?)([a-zA-Z%]+)', input_string)
    return [(float(num), unit) for num, unit in matches]

def extract_value_and_unit(text):
    # Define the regular expression pattern
    pattern = r'(?P<value>\d*\.?\d+)\s*(?P<unit>[a-zA-Z/]+)'
    
    # Find all matches in the text
    matches = re.finditer(pattern, text)
    
    # Initialize lists to store extracted values and units
    values = []
    units = []
    
    # Iterate over matches to extract values and units
    for match in matches:
        value = float(match.group('value'))
        unit = match.group('unit').strip()
        values.append(value)
        units.append(unit)
    
    return values, units



def parse_description_sections(desc_section, all_headers, header_samples, full_link):
    description = ''
    warning = ''
    package_contents = ''
    ingredients = ''
    key_features = ''
    flavors = ''
    specifications = ''
    performance = ''
    disposable = ''
    why = ''
    preference = ''
    innovation = ''
    enjoyment = ''
    compatibility = ''
    coil = ''
    battery = ''
    puffs = ''
    nicotine = ''
    e_liquid = ''
    prefilled = ''
    devices = ''
    airflow = ''
    heating_element = ''
    operation = ''
    charging = ''
    screen = ''
    links_txt = ''
    colors = ''
    options_txt = ''
    returns = ''
    size = ''
    pods = ''
    hardware = ''
    wattage = ''
    faqs = ''
    vgpg_ratio = ''
    power_mode = ''
    name = ''


    
    functions = [
        str.upper,
        str.lower,
        str.capitalize,
        str.title,
        str.swapcase,
        str.casefold
    ]
    section_strings = dict()
    for k, v in section_strings_raw.items():
        key = k
        section_strings[key] = v
        if key.endswith(':'):
            key = key.replace(':', '')
            section_strings[key] = v
            
            key = key.strip() + '-'
            section_strings[key] = v
            key = key.strip() + '--'
            section_strings[key] = v
            key = key.strip() + ' - '
            section_strings[key] = v
        else:
            key = key.strip() + ':'
            section_strings[key] = v
            
            key = key.strip() + '-'
            section_strings[key] = v
            key = key.strip() + '--'
            section_strings[key] = v
            key = key.strip() + ' - '
            section_strings[key] = v
            
        key = key.strip() + '::'
        section_strings[key] = v
        
        for func in functions:
            key = func(k)
            section_strings[key] = v
            if key.endswith(':'):
                key = key.replace(':', '')
                section_strings[key] = v

                key = key.strip() + '-'
                section_strings[key] = v
                key = key.strip() + '--'
                section_strings[key] = v
                key = key.strip() + ' - '
                section_strings[key] = v
            else:
                key = key.strip() + ':'
                section_strings[key] = v

                key = key.strip() + '-'
                section_strings[key] = v
                key = key.strip() + '--'
                section_strings[key] = v
                key = key.strip() + ' - '
                section_strings[key] = v

            key = key.strip() + '::'
            section_strings[key] = v
        
    
    section_map = {
        'description': description,
        'warning': warning,
        'package_contents': package_contents,
        'ingredients': ingredients,
        'key_features': key_features,
        'flavors': flavors,
        'specifications': specifications,
        'performance': performance,
        'disposable': disposable,
        'why': why,
        'innovation': innovation,
        'preference': preference,
        'enjoyment': enjoyment,
        'compatibility': compatibility,
        'coil': coil,
        'battery': battery,
        'puffs': puffs,
        'nicotine': nicotine,
        'e_liquid': e_liquid,
        'prefilled': prefilled,
        'devices': devices,
        'airflow': airflow,
        'heating_element': heating_element,
        'operation': operation,
        'charging': charging,
        'screen': screen,
        'links': links_txt,
        'colors': colors,
        'returns': returns,
        'options': options_txt,
        'size': size,
        'pods': pods,
        'hardware': hardware,
        'wattage': wattage,
        'faqs': faqs,
        'vgpg_ratio': vgpg_ratio,
        'power_mode': power_mode,
        'name': name
    }
    if desc_section:
        cur_section = 'description'
        if desc_section:
            headers = [tag.text for tag in desc_section.find_all(lambda tag: tag.name in ['strong','h1', 'h2', 'h3', 'h4', 'h5'])]
            stext = desc_section.get_text(separator='\n').split('\n')
            for s in stext:
                s = s.strip()
                if s == '':
                    continue
                s_no_colon = s.replace(':', '').strip()
                if s in section_strings:
                    cur_section = section_strings[s]
                elif s_no_colon in section_strings:
                    cur_section = section_strings[s_no_colon]
                elif s.lower().startswith('why') and s.endswith('?'):
                    cur_section = 'why'
                elif 'features:' in s.lower():
                    cur_section = 'key_features'
                elif s in headers:
                    all_headers.append(s)
                    header_samples[s] = full_link
                    header_counter = Counter(all_headers)
                    #if header_counter[s] > 5:
                    #    print(s, full_link)
                    cur_section = 'description'
                    section_map[cur_section] += f'{s}\n\n'
                else:
                    section_map[cur_section] += f'{s}\n'
    return section_map


# Function to download and save an image
MIN_IMAGE_BYTES = 10 * 1024


def download_image(url, tag, save_dir='getpop_images', alt='', number_append=None, referer=None, cookies=None, allow_small=False):
    if not url:
        print("No URL provided for image download.")
        return None
    if not tag:
        print("No tag provided for image download.")
        return None
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:92.0) Gecko/20100101 Firefox/92.0'
    }
    if referer:
        headers['Referer'] = referer
        headers['Accept'] = 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8'
    image_info = dict()
    main_dir = os.getenv('BOX_DIR')
    final_dir = os.path.join(main_dir, save_dir)
    # Create the directory if it doesn't exist
    if not os.path.exists(final_dir):
        os.makedirs(final_dir)
    image_extension = url.split('.')[-1].split('?')[0].split(':')[0]  # Extract file extension from URL
    if number_append is not None:
        tag = f"{tag}_{number_append}"
    save_path = os.path.join(final_dir, f'{tag}.{image_extension}')
    # if os.path.exists(save_path):
    #     #print(f"File already exists at {save_path}. Skipping download.")
    #     return
    try:
        response = requests.get(url, headers=headers, cookies=cookies, timeout=45)
        response.raise_for_status()  # Check for request errors
        if len(response.content) < MIN_IMAGE_BYTES and not allow_small:
            return None
        img = Image.open(BytesIO(response.content))

        width, height = img.size
        if width < 100 or height < 100:
            return None
        img.save(save_path)
        image_info['url'] = url
        image_info['path'] = save_path
        image_info['alt'] = alt
        #print(f"Image saved: {save_path}")
    except Exception as e:
        print(f"Failed to download {url}: {e}")
        return None
    return image_info


def download_image_batch(images, tag, save_dir, referer=None, cookies=None):
    """Download product images, retaining a small image only as a last resort."""
    candidates = []
    seen = set()
    for image in images or []:
        if isinstance(image, str):
            image = {'url': image, 'alt': ''}
        url = image.get('url') if image else None
        if url and url not in seen:
            seen.add(url)
            candidates.append(image)

    records = []
    for number, image in enumerate(candidates, start=1):
        saved = download_image(
            image['url'], tag, save_dir=save_dir, alt=image.get('alt', ''),
            number_append=number, referer=referer, cookies=cookies,
        )
        if saved:
            records.append(saved)

    if records or not candidates:
        return records

    # Every available candidate was under 10 KB, so retain the first one.
    fallback = download_image(
        candidates[0]['url'], tag, save_dir=save_dir, alt=candidates[0].get('alt', ''),
        number_append=1, referer=referer, cookies=cookies, allow_small=True,
    )
    return [fallback] if fallback else []


def download_image_records(images, tag, save_dir, referer=None, cookies=None):
    return download_image_batch(images, tag, save_dir, referer=referer, cookies=cookies)
        
puff_regex = re.compile(r'(?:puff(?:s?\s*count)?:\s*)?(\d+(?:,\d+)?(?:-\d+)?(?:k)?(?:[+]?))(?:\s*puffs?)', flags=re.IGNORECASE)
nico_regex = re.compile(r'([1-9]\.[0-9]{1,2}|[1-9][0-9]|[0-9])\s*(?:%|mg/ml)', flags=re.IGNORECASE)
nico_regex2 = re.compile(r'(?:salt\s*nicotine:\s*)?([1-9]\.[0-9]{1,2}|[1-9][0-9]|[0-9])\s*%?\s*salt\s*nicotine?', flags=re.IGNORECASE)
device_regex = re.compile('(disposable|rechargeable|battery|mesh coil|USB|Adjustable Airflow)', flags=re.IGNORECASE)
ml_regex = re.compile(r'(\d+(?:,\d{3})?)\s*ml', flags=re.IGNORECASE)
battery_regex = re.compile(r'(?:battery\s*(?:capacity)?:?\s*)?(\d+)\s*mah', flags=re.IGNORECASE)


def extract_battery(txt):
    battery = ''
    battery_ = battery_regex.search(txt)
    if battery_:
        battery = battery_.group(1)

    if len(battery) > 0 and 'mah' not in battery.lower():
        battery += 'mAh'
    return battery

def find_features(txt, section=None):
    p_text = ''
    n_text = ''
    ml_text = ''
    flav_text = []
    dev_text = []
    
    if section:
        txt2 = txt + ' ' + section
    else:
        txt2 = txt
    
    any_found = False
    puffs = puff_regex.search(txt)
    if puffs:
        p_text = (puffs.group(0))
        any_found = True

    
    nico = nico_regex.search(txt2)
    if nico:
        n_text = (nico.group(0))
        any_found = True
    else:
        nico2 = nico_regex2.search(txt2)
        if nico2:
            n_text = (nico2.group(0))
            any_found = True
            
    dev = device_regex.findall(txt)
    if dev:
        dev_text = dev
        any_found = True
        
    ml_ = ml_regex.search(txt)
    if ml_:
        ml_text = ml_.group(0)
        any_found = True
        
    flav_ = flavor_regex.findall(txt)
    if flav_:
        flav_text = flav_
        any_found = True
        
    return any_found, p_text, n_text, ml_text, flav_text, dev_text


def features_to_cats(feats):
    fl1 = ''
    fl2 = ''
    fl3 = ''
    fl5 = ''
    fl4 = ''
    disposable = ''
    recharge = ''
    battery = ''
    mesh = ''
    usb = ''
    adjustable = ''


    found_flavs = list()
    pe = ''
    pu = ''
    ml = ''
    for feat_ in feats:
        _, puffs_res, nico_res, ml_res, flav_text, dev_text = feat_
        if puffs_res and puffs_res != '':
            pu = puffs_res.lower().replace('puffs', '').replace(',', '').strip()
        if nico_res and nico_res != '':
            pe = nico_res.lower().replace('salt nicotine', '').replace('nicotine', '').strip()
        if ml_res and ml_res != '':
            ml = ml_res.lower().replace('ml', '').strip()
        if flav_text and len(flav_text) > 0:
            for ft in flav_text:
                found_flavs.append(ft.lower())

        if dev_text and  len(dev_text) > 0:
            #print(dev_text)
            for ft in dev_text:
                ft = ft.lower()
                #disposable','rechargeable','battery','mesh coil','USB','Adjustable Airflow',
                if 'disposable' == ft:
                    disposable = True
                if 'rechargeable' == ft:
                    recharge = True
                if 'battery' == ft:
                    battery = True
                if 'mesh coil' == ft:
                    mesh = True
                if 'usb' == ft:
                    usb = True
                if 'adjustable airflow' == ft:
                    adjustable = True
    found_flavs = sorted(list(set(found_flavs)))

    if len(found_flavs) == 5:
        fl1 = found_flavs[0]
        fl2 = found_flavs[1]
        fl3 = found_flavs[2]
        fl4 = found_flavs[3]
        fl5 = found_flavs[4]
    if len(found_flavs) == 4:
        fl1 = found_flavs[0]
        fl2 = found_flavs[1]
        fl3 = found_flavs[2]
        fl4 = found_flavs[3]
    if len(found_flavs) == 3:
        fl1 = found_flavs[0]
        fl2 = found_flavs[1]
        fl3 = found_flavs[2]
    if len(found_flavs) == 2:
        fl1 = found_flavs[0]
        fl2 = found_flavs[1]
    if len(found_flavs) == 1:
        fl1 = found_flavs[0]
        
    return disposable,recharge,battery,mesh,usb,adjustable,found_flavs
