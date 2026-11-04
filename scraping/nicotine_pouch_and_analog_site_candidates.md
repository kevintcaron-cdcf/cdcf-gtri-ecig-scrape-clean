# Potential Nicotine-Pouch and Nicotine-Analog Sites to Scrape

## Existing local coverage

The local scraping directories appear to focus primarily on vape retailers:

- CSVape
- Element Vape
- GetPop
- Mi-Pod
- My Vapor Store
- Perfect Vape
- Vape.com
- VapeSourcing
- VapeWH
- Vaping.com

Dedicated nicotine-pouch retailers and several nicotine-alternative/analog sellers do not appear to be represented in the existing site folders.

## Highest-priority candidates

| Site | URL | Products / relevance | Scraping difficulty |
|---|---|---|---|
| Prilla | https://prilla.com/us/nicotine-pouches | 600+ nicotine-pouch products, gum, lozenges, tablets; brands include ALP, FRE, Lucy, XQS, ZEO, ZIMO, White Fox, Bridge, NYKD, and others | Easy–moderate |
| Nicokick | https://nicokick.com/us/nicotine-pouches | 190+ nicotine-pouch products, gum, lozenges, tablets, and alternative oral products | Easy–moderate |
| Northerner | https://www.northerner.com/us/nicotine-pouches | ZYN, VELO, Rogue, CLEW, FRE, Sesh+, ALP, Lucy, Juice Head, Grizzly, ZEO, and others | Moderate |
| ALP Pouches | https://alppouch.com/collections/all-products | Official ALP nicotine-pouch and caffeine-product catalog; includes Frontier Collection | Easy |
| Sesh Products | https://seshproducts.com/collections/nicotine-pouches | Official Sesh+ catalog with 4, 6, and 8 mg products | Easy |
| Juice Head | https://juicehead.com/collections/nicotine-pouches | Official fruit-flavored nicotine-pouch catalog | Easy |
| Outlaw Dip | https://outlawdip.com/collections/pouches | Tobacco-free dip, oral pouches, nicotine-alternative products, and caffeine pouches | Easy |
| Spree Bar Sales | https://spreebarsales.com/ | Direct seller of Metatine-containing disposable products | Easy–moderate |
| Kumi Six | https://www.kumisixofficial.com/ | Official NoNic6/SFN disposable-device and pod product discovery | Easy for discovery; retailer needed for pricing |
| SBX Vape Sales | https://sbxvapesales.com/ | Metatine disposable products | Easy–moderate |
| West Coast Vape Supply | https://westcoastvapesupply.com/collections/metatine-nicotine | SBX Metatine products with detailed descriptions and warnings | Easy |

- https://nicpouches.us/

## Recommended first three

### 1. Prilla

Prilla is likely the strongest initial target because it exposes a large catalog with:

- Product name
- Brand
- Flavor
- Nicotine strength
- Pouch format
- Pouches per can
- Pack size
- Price and sale price
- Availability
- Product URL
- Reviews and ratings for many products

The category is paginated with ordinary query parameters:

```text
https://prilla.com/us/nicotine-pouches?page=1
https://prilla.com/us/nicotine-pouches?page=2
```

The HTML appears sufficiently server-rendered for a conventional `requests` plus BeautifulSoup scraper. It appears to use a Magento-style catalog, making pagination and product URLs relatively predictable.

Useful categories:

```text
/us/nicotine-pouches
/us/other-nicotine-products
/us/nicotine-gum
/us/nicotine-lozenges
/us/nicotine-tablets
/us/products-containing-synthetic-nicotine
/us/products-containing-plant-derived-nicotine
/us/zyn-alternatives
```

### 2. Nicokick

Nicokick is useful because it covers product types that are not limited to pouches:

- Nicotine pouches
- Nicotine gum
- Nicotine lozenges
- Nicotine tablets
- Cotton Mouth-style oral products
- Brands including CLEW, FRE, Juice Head, Sesh+, ALP, Lucy, ZEO Universe, and zone

Pagination appears predictable:

```text
https://nicokick.com/us/nicotine-pouches
https://nicokick.com/us/nicotine-pouches?p=2
https://nicokick.com/us/nicotine-pouches?p=3
```

Useful endpoints:

```text
/us/nicotine-pouches
/us/nicotine-pouches/brands
/us/nicotine-lozenges
/us/nicotine-gum
/us/nicotine-tablets
/us/other-products
```

The site appears to use Magento/Hyvä conventions. Product cards expose product name, brand, flavor, strength, pack quantities, prices, ratings, and product links in the server response.

### 3. Outlaw Dip

Outlaw is a strong target for emerging nicotine-alternative and oral-product surveillance. It exposes:

- Oral pouch products
- Tobacco-free dip
- Nicotine-alternative products
- Caffeine and energy pouches
- Flavor and cut classifications
- Strength variants
- Pack-size pricing

Likely Shopify collection pages:

```text
https://outlawdip.com/collections/pouches
https://outlawdip.com/collections/outlaw-dip
https://outlawdip.com/collections/reloads-pouches
https://outlawdip.com/collections/energy-pouches
```

Check Shopify structured endpoints before using browser automation:

```text
/collections/pouches/products.json
/collections/outlaw-dip/products.json
/sitemap_products_1.xml
```

## Nicotine-analog targets

### Spree Bar

- Product site: https://spreebar.com/products
- Sales site: https://spreebarsales.com/

Products are marketed with proprietary **Metatine**, described as a synthetic nicotine analog/6-methyl nicotine alternative. Product pages include flavor, device type, puff count, and marketing claims. The sales site is likely more useful than the corporate product site because it exposes purchase-oriented listings.

### Kumi Six

- Official site: https://www.kumisixofficial.com/
- Retailer: https://vaperanger.com/brands/kumi-six-by-well-versed/

Kumi uses terms such as **NoNic6** and **SFN** (“substitute for nicotine”). The official site is useful for product and flavor discovery, while VapeRanger is more useful for prices and inventory.

### SBX

- Sales site: https://sbxvapesales.com/
- West Coast Vape Supply: https://westcoastvapesupply.com/collections/metatine-nicotine
- VapeRanger: https://vaperanger.com/brands/sbx

SBX products are marketed as containing **Metatine**. West Coast Vape Supply is particularly useful because its category page provides structured descriptions, strength claims, flavor options, and pricing.

### Katchmi

Mi-Pod already appears in the local data, so it may already be covered. An additional source is:

- https://vaping.com/collections/katchmi

Katchmi uses **Nixodine**, marketed as a nicotine alternative. Add Vaping.com only if the existing scraper does not already include this domain.

## Other specialty retailers

- SnusExpress: https://www.snusexpress.com/us/en/nicotine-pouches
- MyNicco: https://mynicco.com/
- N Pouches: https://npouches.com/
- Rushnic: https://rushnic.com/collections/tobacco-free-nicotine-pouches
- DarePouch: https://darepouch.com/
- Native Smokes 4 Less: https://nativesmokes4less.su/product-category/nicotine-pouches/
- The Electronic Cigarette Company: https://www.theelectroniccigarette.co.uk/snus-nicotine-pouches
- VapeRanger: https://vaperanger.com/
- Whitelip: https://whitelip.com/

## Suggested implementation order

1. Prilla — broad catalog and easy structured pagination.
2. Nicokick — broad U.S. coverage and alternative oral products.
3. Outlaw Dip — Shopify collections and analog-adjacent oral products.
4. ALP — official catalog and new-product monitoring.
5. Sesh Products — small, clean official catalog.
6. Spree Bar Sales — direct analog-product monitoring.
7. SBX sales and retail pages — Metatine products.
8. Kumi Six and VapeRanger — NoNic6/SFN products.
9. Northerner — valuable but potentially more dynamic.
10. SnusExpress, MyNicco, and DarePouch — international and high-volume expansion.

## Suggested schema fields

```text
product_name
brand
site_name
url
category
sub_category
product_type
flavor
nicotine_strength
nicotine_strength_unit
analog_name
active_ingredient
pouches_per_can
pack_size
format
cut
moisture_or_pouch_type
price
sale_price
availability
country_or_region
manufacturer
ingredients
warnings
marketing_claims
date_scraped
```

For analog products, preserve the exact marketing terminology rather than normalizing it away:

```text
Metatine
6-MN
6-methyl nicotine
Nixodine
Nixamide
NoNic6
SFN
NIC-SAFE
```

These terms may be important because products can be marketed as “nicotine-free” while still being positioned as nicotine substitutes or receptor-active analogs. Capture the disclaimer and regulatory language verbatim for later review.

## Compliance and operational notes

Before production collection, check each site's:

- `robots.txt`
- Terms of service
- Age-gate behavior
- Rate limits
- State and country shipping restrictions
- Product availability and regional filtering

Use a conservative request rate and avoid collecting checkout, customer-account, or age-verification data.
