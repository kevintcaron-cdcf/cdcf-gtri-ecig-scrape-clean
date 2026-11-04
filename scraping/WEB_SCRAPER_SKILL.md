# Web Scraper Skill for This Project

This document is the implementation guide for adding a new retailer scraper to this repository. It is based on the completed, active, non-archive scrapers in `scraping/`:

- `elementvape.py`
- `getpop.py`
- `myvaporstore.py`
- `puffco.py`
- `vapesourcing.py`
- `vapewh.py`

`scraping/in_development/gopuff.py` is not included in the normal production run. It contains a conservative rebuilt implementation, but it remains production-unverified until a live sample confirms the current GoPuff selectors, access behavior, and database output. Its site-specific assumptions are called out separately near the end of this document.

The goal is not merely to download product pages. A successful scraper in this project must discover products reliably, preserve the source HTML, extract useful structured fields, download images into the Box-synced directory, and write repeatable updates to the Azure SQL ecig database.

## 1. Repository and Runtime Context

Run scripts from the repository root. Existing scripts assume this working directory because `db/db_azure.py` loads `.env` using `os.getcwd()` and the scrapers use paths such as `scraping/data-latest/`.

The target catalog is USA-focused. Exclude country-specific storefronts unless
the USA catalog, shipping scope, and product availability are explicitly
verified. ISP blocks and retailer anti-bot blocks are access constraints, not
selector problems; record them in `scraping/SITE_INVENTORY.md` and do not
hammer the site with repeated retries.

Typical setup:

```bash
source venv/bin/activate
pip install -r requirements.txt
python scraping/<new_scraper>.py
```

The runtime uses:

- Python
- `requests` for direct HTTP requests and image downloads
- `BeautifulSoup` for parsing HTML
- Selenium with Firefox for JavaScript-rendered pages, age gates, consent dialogs, lazy loading, infinite scroll, and load-more controls
- Pillow to validate and save images
- `python-dotenv` for configuration
- `pyodbc` for Azure SQL

The existing scrapers commonly use `sys.path.append(...)` followed by:

```python
from db.db_azure import *
from ecig_parsing import *
```

Prefer explicit imports in new work, but preserve the repository's import behavior if the scraper is being added in the same style.

## 2. Configuration and Secrets

Do not hard-code credentials, database names, or the Box path. `.env` supplies the values consumed by `db/db_azure.py`:

```text
DB_NAME=ecig_database
DB_USER=...
DB_PASSWORD=...
DB_HOST=your-server.database.windows.net
DB_DRIVER={ODBC Driver 18 for SQL Server}
DB_ENCRYPT=yes
DB_CONNECTION_TIMEOUT=30
BOX_DIR=/Users/<user>/Library/CloudStorage/Box-Box/<Box project folder>/
```

The database is the Azure SQL ecig database configured by `DB_HOST`, `DB_NAME`, `DB_USER`, and `DB_PASSWORD`. The connection helper builds an encrypted SQL Server connection using parameter placeholders (`?`). Never print passwords or connection strings.

Azure SQL writes must use bounded retries and always close cursors and
connections in `finally` blocks. Connection exhaustion is a transient
operational failure: retry a small number of times with backoff, then log the
failure and let the scraper continue rather than terminating the full run.

`BOX_DIR` must point to the locally synced Box project folder. `download_image()` in `scraping/ecig_parsing.py` creates the requested image subdirectory beneath `BOX_DIR` and returns a record containing:

```python
{
    "url": original_image_url,
    "path": absolute_or_box_path,
    "alt": image_alt_text,
}
```

The database stores this returned `path` in `ecig_images.path`; it does not upload image bytes to SQL. Make sure Box is mounted/synchronized before running a scraper.

Image downloads use the shared `download_image_batch()` policy. Candidate images
under 10 KB are skipped unless every available candidate is under 10 KB, in
which case the first candidate is retained. Existing products should query
`ecig_images` first and download images only when no image record exists.

## 3. Canonical Scraper Shape

Every new scraper should have the following high-level flow:

1. Define the retailer base URL and its database site constant.
2. Define category, brand, or collection entry points.
3. Fetch each listing page, using Selenium only where the site requires rendered content.
4. Identify product cards and extract the product URL, title, tag, listing price, and listing image.
5. Fetch each product page once and cache the HTML in an in-memory `found` dictionary.
6. Parse the product page into the project data contract.
7. Download valid product images to a Box subdirectory.
8. If the product is new, call `map_product_data(site, data)`.
9. If the product already exists, call `sync_ecig_product_history()` with the fully parsed detail record, record price history with `insert_ecig_price()`, add any newly discovered reviews/review attributes, and backfill images only when the product has no image records.
10. Close the Selenium driver even on errors.

Use a script entry point:

```python
if __name__ == "__main__":
    main()
```

Use one long-lived Selenium driver per scraper where possible. Creating a new browser for every listing and product page is slower and more likely to fail. The current scrapers vary in this respect; a new scraper should improve on that pattern rather than copy the least efficient version.

## 4. URL Discovery and Pagination

### Category Priority

Production scrapers should process categories in this order so high-value product coverage is completed first:

1. New arrivals, newest products, new releases, and new-vape categories when the retailer exposes them. Within that group, disposable and disposable-adjacent new products come first.
2. Other disposable vapes and disposable-adjacent products, including puff-count, rechargeable-disposable, screen, low-nicotine, and Nixodine categories.
3. Closed refills and pod products, including replacement pods/cartridges, prefilled products, pod systems, refillable vape categories, and nicotine salts.
4. E-liquids, e-juice, vape juice, and salt-nic liquid categories.
5. Miscellaneous equipment and accessories, including kits, mods, tanks, batteries, chargers, vaporizers, and hardware.
6. THC and delta-product categories last.

Use the shared `prioritize_links()` helper from `scraping/ecig_parsing.py` to preserve the declared order within each priority group while avoiding random category ordering. Priority terms are only an ordering mechanism, never an allowlist: category discovery must retain every valid catalog/category/brand link so newly added products are not excluded.

### Category Discovery Is Additive

- Hardcoded links are fallback seeds and priority hints, not the complete catalog.
- A scraper should inspect the retailer's current navigation and category pages, merge newly discovered catalog links with the fallback seeds, deduplicate them, and then apply priority ordering.
- Do not restrict discovery to disposable, e-liquid, pod, or any other named prefix. Those terms determine processing order only.
- Filter only obvious non-catalog routes such as login, cart, account, search, policy, blog, and product-detail URLs.
- Preserve a bounded page limit and block detection so broader discovery cannot turn into unbounded crawling.

### Entry points

Retailers expose products through different structures:

- Shopify collections: `/collections/...`
- BigCommerce-style category pages: paths ending in `-s/<id>.htm`
- Magento-style categories and brand pages: `.html` paths
- Curated retailer pages: `/pages/...` or custom collection pages

Keep entry points explicit in a `links` list. Include all relevant product categories, brands, new arrivals, clearance, and special collections. Avoid relying on one “all products” page unless it is proven complete.

Record the category used for discovery as `site_category`. Existing scripts derive this from the URL, for example by removing `/collections/` or splitting a category path. Normalize it consistently and do not let query parameters become the category.

### Pagination

Stop pagination only when the page has no product cards. Also apply a safety limit for sites that return the same page forever. The working scrapers use combinations of:

- `?page=<n>` pagination
- a site-reported total page count
- stopping at zero cards
- a maximum page guard such as 20 or 25
- Selenium infinite scroll until document height stops changing
- clicking `Load More` until the control disappears

Always verify that the requested page number is actually used. In `puffco.py`, the loop builds `page_url` but fetches `url`, which can repeatedly scrape the first page. Treat this as a bug pattern, not a template.

Deduplicate discovery. The same product frequently appears in multiple collections and the source link lists may contain duplicates. Use a `seen_tags` or `seen_urls` set in addition to the HTML cache.

## 5. Fetching Strategy

Use direct `requests` first when the HTML contains the needed data. Use Selenium when the page needs:

- JavaScript rendering
- age verification
- discount or newsletter modal dismissal
- lazy-loaded product cards/images
- infinite scrolling
- “Load More” clicks
- review iframe or widget rendering

A robust fetch helper should:

- set a realistic page-load timeout
- use headless Firefox by default
- wait for a meaningful element, not only `<body>`, when possible
- handle optional age/consent/discount dialogs without failing the whole scrape
- scroll or click controls only when needed
- return a direct-request fallback if Selenium fails
- always quit/close the driver in `finally`
- log the URL and failure reason

The existing sites demonstrate several dialog patterns:

- Element Vape: click `yes, i am of legal age`
- Get Pop: click `I am 21+`
- Vape Sourcing: click `.age-yes`, optionally dismiss “No thanks, I'll pay full price”
- Puffco: click `Yes`, optionally close `voyage-close`
- Vape WH: click `ac-ag-yes-button`, optionally dismiss the full-price prompt

These selectors are site-specific. Make them optional and catch `TimeoutException`, `NoSuchElementException`, and stale/interactability failures. A missing optional modal must not discard otherwise valid page HTML.

Use `page_load_strategy = 'eager'` where appropriate, then wait for the product-card selector or a known content container. Fixed sleeps may still be needed for lazy content, but prefer explicit waits and bounded polling.

## 5A. Rate Limiting, Blocks, and Anti-Bot Responses

Rate limiting is a normal operational condition, not an error to defeat by sending requests faster or continuously changing identities. A scraper must respect the retailer's terms, robots guidance where applicable, published API limits, and any explicit response to stop or reduce traffic. If a site prohibits automated access, stop and use an approved feed, API, or data provider instead.

### Detect the condition

Classify responses before parsing them. Treat these as possible rate-limit or anti-bot responses:

- HTTP `429 Too Many Requests`
- HTTP `403 Forbidden` after a burst of requests
- repeated `5xx` responses
- `Retry-After` headers
- CAPTCHA or challenge pages
- “Access denied”, “verify you are human”, or suspiciously short HTML
- a normal HTTP `200` response with no expected product selector
- a sudden drop from normal page length/card count to an empty shell

Do not cache a block page as valid product HTML. Store a separate fetch outcome containing URL, timestamp, status code, response length, detected block reason, and retry-after value. This makes it possible to resume without mistaking an access-denied page for a page with zero products.

### Use a conservative request policy

Start with the lowest request rate that completes the job. For this project, a sensible default is:

- one sequential product fetch at a time per retailer
- a delay between requests, with random jitter to avoid synchronized bursts
- a longer delay between category pages
- no parallel browser sessions unless the site explicitly permits the load
- a per-domain request budget for each run
- a maximum retry count and a maximum total runtime
- stop the run after repeated blocks instead of hammering the site

Use exponential backoff with jitter. Honor `Retry-After` when supplied and cap the backoff so a broken site does not create an unbounded process:

```python
import random
import time


def wait_before_retry(attempt, retry_after=None, base=5, cap=300):
    if retry_after is not None:
        delay = min(float(retry_after), cap)
    else:
        delay = min(base * (2 ** attempt), cap)
    delay += random.uniform(0, min(5, delay * 0.25))
    time.sleep(delay)
```

Only retry failures that are plausibly transient. Do not retry malformed URLs, permanent `404` responses, a clear “do not crawl” response, or a CAPTCHA indefinitely. For `429`, `503`, connection resets, and timeouts, pause and retry within a small bound. For repeated `403` or challenge pages, stop or switch to an approved access method.

### Separate discovery from detail fetching

Do not fetch every product page on every run. Use a two-stage schedule:

1. Fetch category pages slowly and identify new or changed product URLs.
2. Fetch detail pages only for new products, products whose listing data changed, or products due for a periodic refresh.

Existing products can often receive a price check without downloading the full page. Reviews and full descriptions should have their own refresh cadence. This reduces load and is more reliable than trying to make a high-volume run “look human.”

### Cache successfully fetched content

Persist successful HTML by canonical URL, preferably with a timestamp and content hash. Reuse it during parser development and reruns. Crawl4AI supports explicit cache modes such as `CacheMode.ENABLED`, `READ_ONLY`, `WRITE_ONLY`, `BYPASS`, and `DISABLED`; use `READ_ONLY` for offline parser work and normal enabled caching for repeatable crawls. Use `BYPASS` only when a fresh page is genuinely required.

The existing GoPuff scraper's file cache is a useful direction, but it should be improved by:

- storing status and metadata alongside HTML
- writing only successful, sufficiently complete pages
- canonicalizing URLs before hashing
- adding an expiration policy
- keeping block pages out of the success cache
- separating discovery/listing cache from product-detail cache

### Reuse a browser session

Repeatedly creating a browser for each URL increases startup cost and can produce an unnatural request pattern. Prefer one sequential browser session per retailer and reuse cookies, age verification, locale, and other state. Crawl4AI supports `session_id` for sequential session reuse; its documentation specifically cautions that session reuse is for sequential workflows, not parallel operations.

The session should be closed explicitly after the run. If the session begins returning challenge pages, discard it, wait, and resume later rather than repeatedly refreshing it.

### Crawl4AI as an optional fetch layer

Crawl4AI can be useful when a retailer needs browser rendering, controlled JavaScript actions, session reuse, cache control, structured CSS extraction, or a fallback fetch function. It is not a guarantee of access and should not be treated as a magic anti-bot bypass. Adding Crawl4AI also introduces an asynchronous runtime and browser-installation requirements, so keep the existing `requests`/Selenium path for working sites unless Crawl4AI solves a demonstrated problem.

For a new difficult site, evaluate it in this order:

1. Direct `requests` with normal caching and conservative pacing.
2. A reusable Selenium or Crawl4AI browser session with explicit waits.
3. An official API, product feed, or retailer-approved export.
4. A reputable external scraping service, only if its use is permitted and the project can protect its credentials and budget.

Crawl4AI's documented anti-bot fallback features include bounded retries, optional proxy configuration, and a `fallback_fetch_function`. If used, configure very small retry counts, inspect `result.success`, `result.error_message`, and `result.crawl_stats`, and record which method resolved the fetch. Do not blindly combine several proxies with repeated retries: the documented worst case multiplies retry rounds by the number of proxies and can create substantial extra traffic.

Example of a conservative Crawl4AI configuration pattern:

```python
from crawl4ai import AsyncWebCrawler, CacheMode
from crawl4ai.async_configs import BrowserConfig, CrawlerRunConfig


async def fetch_with_crawl4ai(url):
    browser = BrowserConfig(headless=True)
    run = CrawlerRunConfig(
        cache_mode=CacheMode.ENABLED,
        max_retries=1,
        wait_until="load",
    )
    async with AsyncWebCrawler(config=browser) as crawler:
        result = await crawler.arun(url=url, config=run)
        if not result.success:
            raise RuntimeError(result.error_message or "Crawl failed")
        return result.html
```

Use Crawl4AI's session features for sequential dynamic navigation, and use a CSS or XPath extraction strategy only after the raw HTML has been validated. Preserve the returned HTML in the same way as Selenium output so the downstream BeautifulSoup parsers and database contract remain unchanged.

### Proxies and identity changes

Do not rotate proxies or user agents as the first response to a block. Random user-agent rotation can itself be a detection signal, and proxy rotation does not fix an excessive request rate. If a proxy is necessary for a legitimate operational reason, use a stable, authorized proxy, keep the request rate low, and document it in configuration rather than embedding credentials in code.

Never use proxies, stealth settings, CAPTCHA-solving, or fingerprint changes to bypass access restrictions or an explicit prohibition. If direct access is blocked, pause and pursue an approved API/feed/provider or request permission.

### Circuit breaker and resume behavior

Implement a per-site circuit breaker. For example, after three block signals within a rolling window:

- stop issuing requests to that domain
- persist the queue of unprocessed URLs
- persist the last successful category/product
- record the block reason and next eligible retry time
- exit cleanly with a nonzero status or a clearly visible warning

On the next run, resume from the saved queue after the cooldown. Do not restart from the first category and repeat the same blocked requests.

### Operational logging

Log aggregate metrics rather than sensitive request details:

- pages attempted, succeeded, skipped, and blocked
- response status counts
- average and maximum delay
- retry count and total backoff time
- cache hits and misses
- products discovered versus product pages fetched
- image failures
- database insert/update failures

Never log cookies, authorization headers, proxy passwords, or complete signed URLs.

## 6. HTML Caching and Error Boundaries

All six scrapers use a module-level `found` dictionary to avoid fetching the same URL repeatedly:

```python
found = {}

if url in found:
    html = found[url]
else:
    html = get_html(url)
    found[url] = html
```

Cache both listing pages and product pages. Do not cache an empty or obviously incomplete response as if it were valid. A practical fetch helper should distinguish:

- successful HTML
- empty response
- direct request fallback
- Selenium failure

Catch errors per URL and per product. One malformed card, missing image, or broken review widget should not stop the entire retailer run. Log the tag and URL, then continue.

## 7. Product Identity and Idempotency

The stable identity used by this project is:

```python
product_id = get_product_id(site_name, site_tag)
```

`site_tag` is normally the final product URL slug with query strings and file suffixes removed as appropriate. Normalize it carefully:

- use the canonical product URL when available
- strip leading/trailing whitespace
- remove query strings and fragments
- preserve meaningful hyphens in the slug
- do not use the display title as the primary key
- skip cards with no usable URL/tag

The SQL schema also has a unique constraint on `ecig_product.url`. Therefore URL normalization matters as much as tag normalization.

For a new product:

```python
map_product_data(site_name, product_data)
```

For an existing product:

```python
sync_ecig_product_history(product_id, product_data)
insert_ecig_price(product_id, regular_price, sale_price)
insert_reviews(reviews, product_id)  # if reviews were extracted
# insert_product_images(...) only when not product_has_images(product_id)
```

Do not call `map_product_data()` for an existing product. It inserts a new `ecig_product` row rather than updating the existing product. `sync_ecig_product_history()` compares the current parsed record with the product's tracked fields, updates the current `ecig_product` values only when non-empty parsed values differ, and inserts an `ecig_product_history` snapshot only when a tracked value changes. It intentionally does not track HTML or plain-text changes.

The tracked update fields are title/product name, description, site category, package contents, ingredients, e-liquid contents, puffs, coil, battery text, power level, nicotine level, stock status, and features. For pre-history products, the first sync creates a baseline snapshot. The helper logs whether it inserted a baseline, inserted a changed-field snapshot, or found no tracked changes.

`insert_ecig_price_to_db()` already avoids inserting a duplicate price when the latest price values are unchanged. Existing review insertion also checks for duplicates. Before downloading images for an existing product, use `product_has_images(product_id)`; only call `insert_product_images()` to backfill a product with no image records.

## 8. Required Product Data Contract

Build a dictionary with the keys expected by `db/db_azure.py`. The required keys are `tag` and `html`; the remaining fields should be present even when empty or `None`:

```python
data = {
    "title": title,
    "link": canonical_product_url,
    "site_category": site_category,
    "tag": site_tag,
    "brand": brand,
    "sku": sku,
    "html": product_html,
    "plain_text": product_soup.get_text(" ", strip=True),
    "regular_price": regular_price,
    "sale_price": sale_price,
    "flavor_text": flavor_text,
    "description": description,
    "package_contents": package_contents,
    "features": features,
    "ingredients": ingredients,
    "warnings": warnings,
    "eliquid_contents": eliquid_contents,
    "puffs": puffs,
    "coil": coil,
    "battery": battery,
    "power_level": power_level,
    "nicotine_strength": nicotine_strength,
    "stock_status": stock_status,
    "reviews": reviews,
    "review_attributes": review_attributes,
    "flavor_list": flavor_list,
    "nicotine_strengths": nicotine_strengths,
    "images": image_records,
}
```

`map_product_data()` maps these values to `ecig_product` as follows:

| Scraper key | SQL column |
|---|---|
| `title` | `product_name` |
| `link` | `url` |
| `site_category` | `site_category` |
| `tag` | `site_tag` |
| `brand` | `brand` |
| `html` | `html` |
| `plain_text` | `plain_text` |
| `regular_price` | `price` |
| `sale_price` | `price_sale` |
| `flavor_text` | `flavor_text` |
| `description` | `description` |
| `package_contents` | `package_contents` |
| `features` | `features` |
| `ingredients` | `ingredients` |
| `warnings` | `warnings` |
| `eliquid_contents` | `eliquid_contents` |
| `puffs` | `puffs` |
| `coil` | `coil` |
| `battery` | `battery_text` |
| `power_level` | `power_level` |
| `nicotine_strength` | `nicotine_level_text` |
| `stock_status` | `stock_status` |

The database helper inserts related records for reviews, review attributes, flavors, nicotine levels, and images. It currently does not insert colors or the boolean fields calculated by `features_to_cats()`; do not assume adding those keys to the dictionary will persist them. If those fields become required, update the database layer deliberately and test it separately.

## 9. Parsing Product Cards

Product-card selectors are retailer-specific. The observed patterns are:

- Element Vape: `div.plp-product-list`
- Get Pop: `div.product-card`
- My Vapor Store: a large class-based card container
- Puffco: `div.product-card` with `data-url`
- Vape Sourcing: `li.product-item`
- Vape WH: custom `product-card` elements

Extract as much as possible from the card, but treat the product page as authoritative. A card should at minimum provide:

- title
- URL
- stable tag
- listing price(s)
- a candidate image

Use `isinstance(node, bs4.element.Tag)` before processing nodes when selectors may return mixed BeautifulSoup objects.

Normalize relative URLs:

```python
from urllib.parse import urljoin
full_url = urljoin(BASE, href)
```

Do not use a truthiness test on the wrong variable when validating image URLs. Several older patterns contain checks such as `if url:` inside image loops; the new implementation should check the actual `img_url`.

## 10. Parsing Product Pages

### Text and sections

Capture both raw HTML and flattened text. Raw HTML is important for later analysis and debugging; `plain_text` is useful for search and downstream NLP.

Prefer semantic anchors and stable attributes over generated CSS class names. The working scrapers use:

- headings and accordion summaries for descriptions, warnings, specifications, package contents, and FAQs
- `data-*` attributes for price, stock, review author, review text, and rating
- `<select>` options and swatch values for flavors, colors, sizes, and nicotine strengths
- embedded JSON for variant data when present
- iframes for review widgets

`ecig_parsing.parse_description_sections()` can classify common headings such as Description, Features, Flavors, Ingredients, Package Contents, Warning, Battery, Puffs, Nicotine Strength, Coil, and E-liquid contents. It is tolerant of capitalization and punctuation variants. Use it when a retailer has prose sections rather than reliable field-specific attributes, but retain the complete description as a fallback.

### Options and variants

Options may be represented by:

- `<select><option>`
- radio inputs
- buttons or swatches
- `data-option-*` attributes
- variant JSON in a script tag
- list items beneath a heading

Use the nearby label/heading to determine whether a value is a flavor, color, size, or nicotine option. Do not treat every short list item on the page as a flavor. Exclude prompts such as “Choose”, “Select”, and “Option”. Deduplicate while preserving source order when order is meaningful.

For nicotine levels, the related SQL table expects records like:

```python
{"value": 50, "unit": "mg", "level": None}
```

The database helper also accepts a string and converts it to `{value: string, unit: None, level: None}`, but structured numeric values are preferable. Be careful with values such as `5%`, `50mg`, `0mg`, and `3-12mg`; preserve the original text in `nicotine_strength` even when normalization is uncertain.

### Shared feature extraction

`ecig_parsing.find_features()` scans text for:

- puff counts
- nicotine values
- e-liquid volume in ml
- common flavor words
- disposable/rechargeable/battery/mesh/USB/adjustable-airflow terms

Use this as a supplement, not a replacement for explicit page fields. Regex inference can produce false positives. Keep explicit retailer values when available and only fill missing fields from inferred values. `extract_battery()` is useful for mAh values.

## 11. Reviews

Review widgets differ substantially:

- Get Pop: review cards with custom questions and relative dates
- Element Vape: Yotpo cards
- Vape Sourcing: ordinary review cards with percentage-based stars
- Vape WH: Loox reviews in an iframe
- Other sites may expose review JSON or no reviews at all

Normalize each review to the fields consumed by `insert_reviews_to_db()`:

```python
{
    "date": "YYYY-MM-DD" or None,
    "author": author,
    "rating": numeric_rating,
    "verified_buyer": bool,
    "review_text": text,
    "variant": variant,
    "sweet_level": numeric_or_None,
    "iced_level": numeric_or_None,
    "image_url": image_url_or_None,
    "reply_text": reply_text_or_None,
    "reply_from": reply_author_or_None,
    "attributes": {"Question": "Answer"},
}
```

The insert helper skips blank review text and deduplicates by review text/author/date before checking the database. Do not use a site-specific key such as `content` or `stars` without also mapping it to `review_text` and `rating`.

Relative dates are inherently approximate. If the source provides an absolute date, use it. If it only says “months ago”, document the approximation and return a valid ISO date or `None`; never insert arbitrary display text into a SQL `date` field.

Review iframes need a second fetch. Resolve an iframe-relative source URL, call the renderer/fetch helper, parse the iframe HTML, and keep this failure isolated from product parsing.

## 12. Images and Box Storage

Use the shared helper from `ecig_parsing.py`:

```python
image = download_image(
    image_url,
    site_tag,
    save_dir=f"data_from_sites_v2/{SITE}_images",
    alt=image_alt,
    number_append=image_number,
)
```

The helper:

- uses `BOX_DIR`
- creates the destination directory
- requests the image
- opens it with Pillow
- rejects images smaller than 100x100 pixels
- saves it under a tag-based filename
- returns URL/path/alt metadata

Best practices:

- skip empty URLs, SVGs, data URLs, placeholders, logos, and tracking pixels
- resolve protocol-relative URLs with `https:` or use `urljoin()`
- extract the highest useful resolution from `src`, `data-src`, `srcset`, `data-srcset`, `data-zoom`, or image JSON
- deduplicate image URLs before downloading
- append a stable image number to avoid overwriting gallery images
- keep the original URL in the returned record
- use the product title or image alt as `alt` when present
- continue after one image fails

The helper extracts the extension from the URL. URLs without a useful extension or with unusual CDN query strings should be tested; if needed, add a small, local normalization step before calling it rather than changing shared behavior casually.

The SQL image record uses:

```python
{
    "url": image["url"],
    "path": image["path"],
    "title": image.get("title"),
    "alt": image.get("alt"),
}
```

Only successfully saved images should be passed to `map_product_data()`.

## 13. Prices, Product History, and Existing Products

Preserve regular and sale prices separately. Retailers label these inconsistently (“regular price”, “compare at”, “sale price”, “special price”). Strip currency symbols only when the project convention for the target retailer requires it; the SQL columns are text and existing scrapers commonly preserve formatted price strings.

For an existing product, update the price history even if the product page parser has changed:

```python
insert_ecig_price(product_id, regular_price, sale_price)
```

Do not insert an empty price merely because a selector failed. Prefer `None` for unavailable values and log selector failures so a transient layout change is visible.

When a scraper fetches and parses an existing product detail page, it must also synchronize product history:

```python
sync_ecig_product_history(product_id, data)
```

Call this after building the complete data contract and before continuing with price, review, metadata, or image update work. Do not send card-only or partially parsed data to the history helper: missing/empty values are deliberately ignored, but a complete detail record is needed to detect meaningful retailer changes. The history table is an internal audit trail and should not change tracker-facing scraper behavior.

The standard existing-product sequence is:

1. Fetch and fully parse the detail page into `data`.
2. Call `sync_ecig_product_history(product_id, data)`.
3. Call `insert_ecig_price(product_id, data["regular_price"], data["sale_price"])`.
4. Call `insert_reviews()` and review-attribute helpers when the page exposes reviews; their duplicate checks make repeated runs safe.
5. Check `product_has_images(product_id)` and download/insert images only when it returns false.

History logging should make each outcome visible beneath the product's existing-product log, for example:

```text
	[retailer-product-tag] PRODUCT HISTORY baseline inserted for product_id 123
	[retailer-product-tag] PRODUCT HISTORY change inserted for product_id 123: description, stock_status
	[retailer-product-tag] PRODUCT HISTORY unchanged for product_id 123
```

## 14. Common Failure Modes to Avoid

- Fetching a URL without its page number inside a pagination loop.
- Starting a fresh browser for every card when one driver would suffice.
- Treating an optional age/discount modal as mandatory.
- Caching a failed empty response and silently skipping the rest of a run.
- Using a display title as the product identity.
- Calling `map_product_data()` for a product that already exists.
- Passing review dictionaries with `content` or `stars` but no `review_text` or `rating`.
- Inserting non-ISO relative dates into a SQL date column.
- Passing image URLs without resolving `//cdn...` or relative paths.
- Downloading placeholders, SVG logos, thumbnails, and duplicate `srcset` variants.
- Assuming all images have a simple file extension.
- Assuming all pages expose descriptions in one fixed class.
- Assuming product options are always `<select>` elements.
- Assuming review content is in the main document instead of an iframe.
- Assuming calculated boolean fields are persisted just because they are in the Python dictionary.
- Swallowing exceptions without logging the URL, tag, selector, and error.
- Omitting `html` or `tag`, which are required by `map_product_data()`.
- Forgetting to quit Selenium in a `finally` block.

## 15. Testing a New Scraper Safely

Before a full run:

1. Choose one category URL and one known product URL.
2. Run the fetcher and save or inspect the returned HTML.
3. Confirm the product-card selector returns a nonzero count.
4. Confirm the product URL and normalized tag.
5. Confirm title, price, description, options, and stock extraction.
6. Confirm the image helper creates files under the intended Box subdirectory and rejects tiny/invalid images.
7. Print the final data dictionary keys, but not full HTML or secrets.
8. Check `get_product_id(site, tag)` before insertion.
9. For a known existing product, verify price history, product-history synchronization, missing-review insertion, and image backfill behavior. Confirm a first post-feature run creates a baseline; confirm a second unchanged run creates neither duplicate price nor product-history rows.
10. Run a small sample before enabling every category and page.

Useful checks from the repository root:

```bash
python -m py_compile scraping/<new_scraper>.py
python scraping/<new_scraper>.py
```

After a sample run, verify in Azure SQL that:

- `ecig_product` has the expected `site_name`, `site_tag`, URL, and raw HTML
- prices appear in `ecig_price` only when changed
- `ecig_product_history` has an initial/baseline snapshot for new or first-rescraped products and additional rows only when tracked product fields change
- flavors, nicotine levels, images, reviews, and review attributes are linked to the correct product ID
- image paths point into the Box directory
- rerunning the same sample does not create duplicate product rows

## 16. Recommended New-Scraper Template

Use this as a compact starting point, then replace the selectors and dialog logic:

```python
import os
import sys
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, element

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from db.db_azure import (
    get_product_id,
    insert_ecig_price,
    insert_product_images,
    insert_reviews,
    map_product_data,
    product_has_images,
    sync_ecig_product_history,
)
from ecig_parsing import download_image, find_features, extract_battery

BASE = "https://example.com"
SITE = "EXAMPLE_SITE"  # Add the matching constant to db/db_azure.py first.
LINKS = ["/collections/example"]


def canonical_url(href):
    url = urljoin(BASE, href or "")
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def site_tag(url):
    return canonical_url(url).rstrip("/").split("/")[-1].removesuffix(".html")


def main():
    found = {}
    seen_tags = set()

    # Implement bounded listing pagination and a reusable Selenium/request fetcher.
    for listing_url in LINKS:
        listing_html = fetch(canonical_url(listing_url), found)  # site-specific
        listing_soup = BeautifulSoup(listing_html, "lxml")

        for card in listing_soup.select("<PRODUCT_CARD_SELECTOR>"):
            if not isinstance(card, element.Tag):
                continue
            product_url = canonical_url(card.select_one("<PRODUCT_LINK_SELECTOR>")["href"])
            tag = site_tag(product_url)
            if not tag or tag in seen_tags:
                continue
            seen_tags.add(tag)

            product_id = get_product_id(SITE, tag)
            product_html = fetch(product_url, found)
            soup = BeautifulSoup(product_html, "lxml")
            parsed = parse_product(soup, product_url)  # site-specific

            if product_id:
                sync_ecig_product_history(product_id, parsed)
                insert_ecig_price(product_id, parsed["regular_price"], parsed["sale_price"])
                if parsed["reviews"]:
                    insert_reviews(parsed["reviews"], product_id)
                if not product_has_images(product_id):
                    # Download and insert parsed image candidates here.
                    pass
                continue

            images = []
            for number, image in enumerate(parsed["image_urls"], start=1):
                saved = download_image(
                    image["url"], tag,
                    save_dir=f"data_from_sites_v2/{SITE}_images",
                    alt=image.get("alt", ""),
                    number_append=number,
                )
                if saved:
                    images.append(saved)

            parsed["images"] = images
            parsed["tag"] = tag
            parsed["link"] = product_url
            parsed["html"] = product_html
            parsed["plain_text"] = soup.get_text(" ", strip=True)
            map_product_data(SITE, parsed)


if __name__ == "__main__":
    main()
```

The template intentionally leaves `fetch()`, `parse_product()`, and selectors site-specific. The non-site-specific part is the contract: canonical identity, cached fetching, image persistence, new-versus-existing branching, and use of the database helper.

## 17. Site-Specific Lessons

### Element Vape

- Uses a large explicit category and brand URL list.
- Requires Selenium for age verification, infinite scroll, and load-more behavior.
- Reuses a long-lived Firefox driver.
- Product cards and product pages have distinct parsers.
- Yotpo reviews are parsed from product pages.
- Product pages expose flavor `<select>` elements and gallery images.
- Existing products receive price and review updates; new products receive full insertion.
- The implementation is a good model for a two-stage listing/card plus detail-page scraper.

### Get Pop

- Uses Shopify-like collection pagination.
- Product cards expose title, vendor, link, and price.
- Product descriptions are assembled from highlights and collapsible blocks.
- Review cards include verified status, variants, custom attributes, Ice Level, Sweet Level, and relative dates.
- Product images may be in thumbnails, gallery `srcset`, `data-srcset`, `src`, or `data-zoom`.
- This is the strongest example of retaining review attributes and converting relative review dates.

### My Vapor Store

- Uses category URLs with numeric `.htm` identifiers and classic class/data-attribute markup.
- Requires scrolling and an optional age gate/close dialog.
- Product options need generic nearby-heading discovery rather than one fixed selector.
- Description, warnings, package contents, features, and reviews are in separate structured blocks.
- This scraper shows how to handle product options without relying solely on `<label>` elements.

### Puffco

- Uses Shopify-style collections and a custom age modal plus optional promotional overlay.
- Product pages expose useful JSON variant data in `application/json` scripts.
- Accordions are a reliable source for included items, warranty, returns, and other details.
- The product-page parser is compact and a good model for JSON-plus-accordion extraction.
- Fix the pagination fetch bug before copying its loop: fetch the page URL, not the unpaged collection URL.

### Vape Sourcing

- Uses Magento-like category, brand, and product URLs.
- Requires age-gate handling, optional promotional-dialog handling, incremental scrolling, and sometimes load-more clicks.
- Product detail pages contain structured brand data, feature bullets, pros/cons, package lists, ordering tips, FAQs, options, and reviews.
- Review stars are derived from a percentage style and need normalization to a 1-5 rating.
- The site has many duplicate entry points; deduplication is important.

### Vape WH

- Uses Shopify collections and custom `product-card` elements.
- Requires age verification, optional promotion dismissal, scrolling, and sometimes load-more behavior.
- Product options are discovered from labels/selects and custom variant markup.
- Reviews are in a Loox iframe and require a second HTML fetch.
- The parser extracts structured sections for specs, package contents, warnings, and flavor details.
- This is the best example of isolating iframe review scraping from main product parsing.

### VaporDNA

- VaporDNA is a Shopify storefront using the Judge.me review app.
- Product pages server-render review data in `application/ld+json` Product objects and `.jdgm-rev[data-review-id]` elements.
- Parse `reviewBody`, author, rating, ISO `datePublished`/timestamp, and the `data-verified-buyer` flag into the shared review contract.
- Review JSON-LD may contain only a subset of the visible Judge.me review cards; deduplicate reviews by author, text, and date before calling `insert_reviews()`.
- The Shopify product JSON endpoint is useful for product discovery, but review extraction must use the product HTML page.
- Shopify nicotine options must be converted to `{value: float, unit: string, level: None}` before insertion because `ecig_nicotine_levels.value` is a SQL float; retain complex or unparseable text only in `nicotine_strength`, not in the numeric related table.

### Review Coverage Checklist

- `getpop.py`, `vapesourcing.py`, `vapewh.py`, and `elementvape.py` have site-specific review parsers and call `insert_reviews()` for existing products.
- `vapordna.py` uses Judge.me JSON-LD and server-rendered review cards, then calls `insert_reviews()` for existing products and includes reviews for new products.
- BigCommerce scrapers using `bigcommerce_common.py` (`vaping.py`, `ecigmafia.py`, and `perfectvape.py`) use the shared JSON-LD/review-widget parser and update existing reviews.
- `mipod.py`, `vape_com.py`, `puffco.py`, and `myvaporstore.py` use the shared fallback parser and update reviews when the product page exposes compatible markup.
- A scraper must not manufacture an empty review record. If a site uses a client-only or iframe widget, add a site-specific fetcher and verify it against a live product page before marking review coverage complete.

### GoPuff: Rebuilt but Requires Live Verification

`scraping/in_development/gopuff.py` was rebuilt around the project's shared data contract and rate-limit recommendations. Do not add it to the normal production run until a live sample confirms that GoPuff still exposes the expected markup and permits the intended access.

The implementation now includes:

- category URLs using `/c/<slug>/<opaque-id>`
- product cards identified by `data-testid="ProductTile"`
- product links identified by `data-testid="ProductLink"` or `/p/` URLs
- product names from `data-testid="ProductTileName"`
- prices from `RetailPriceOffered`, `SalePriceOffered`, and `RetailPriceStrikethrough`
- success-only HTML and metadata caching under `scraping/cache/gopuff`
- one stable browser user agent and sequential browser reuse
- bounded retries, `Retry-After` parsing, exponential backoff with jitter, and a circuit breaker
- category pagination with repeated-page detection and a maximum page limit
- product image candidates from `data-srcset`, `srcset`, `src`, and `data-src`
- product detail extraction from a possible `data-testid="grid-item"` container

Before considering it complete, verify at minimum:

- that GoPuff actually returns the expected cards and product pages for the target location/session
- that category pagination or infinite scrolling matches the current site behavior
- that the detail container and image gallery selectors match the current page; the rebuilt parser has safe fallbacks but cannot infer data that is not present
- that product pages populate every database field that GoPuff actually provides; the rebuilt dictionary includes all required `map_product_data()` keys
- whether GoPuff exposes reviews; the rebuilt scraper does not invent review data when the site does not provide a verified compatible widget
- that cached HTML is not stale or incomplete, and that only successful responses are persisted
- that the site constant and database behavior are tested against the Azure SQL ecig database
- that the scraper is rerunnable without duplicate products and that existing products receive price/review updates

The rebuilt GoPuff file still needs a live validation run. In particular, GoPuff may require a location/session selection, may change its `data-testid` attributes, and may expose product data only after client-side requests. If the browser receives a challenge page, the circuit breaker stops the run rather than repeatedly retrying it.

### Mi-Pod and GetPop: Identifiers and Stock

- `ecig_product.sku` is the valid field for retailer SKUs or other retailer identifiers. The database `id` is autogenerated and must not be populated by a scraper. The BigCommerce `BCData.product_attributes` object is the preferred source for `sku`; if no SKU exists, the numeric catalog ID is used as the SKU fallback.
- Mi-Pod uses BigCommerce Stencil markup. Its product pages expose `BCData.product_attributes.sku`, `instock`, and a numeric product ID in the listing card's `data-entity-id`. The scraper stores the SKU, or that numeric catalog ID when the SKU is absent, in `ecig_product.sku` and normalizes `instock` to `In Stock` or `Out of Stock`.
- GetPop's current site revamp also uses BigCommerce Stencil markup. Its product pages expose the same `BCData.product_attributes` fields, with the numeric catalog ID also available in the embedded product event data as `product_id` when needed.
- GetPop no longer uses the old `/collections/...` paths. Current entry points include `/disposables/`, `/e-liquids/`, `/pod-systems/`, `/devices/`, `/pods/`, and `/nicotine-pouches/`.
- `og:availability` is a fallback stock source for both sites. `instock` and `in stock` normalize to `In Stock`; `oos` and `outofstock` normalize to `Out of Stock`.
- The Azure insert mapper must explicitly pass `sku`; otherwise the database insert silently writes `NULL` to the field. Do not add or write fields that are not present in the live `ecig_product` schema.

### Vape WH: Headed Browser Fallback

- Vape WH may return HTTP `403` or an empty page to direct requests and headless Firefox even when the site is available in a normal browser session.
- The age/access gate is optional and should not be treated as a required element. A missing `#ac-ag-yes-button` means the session may already have the required cookie.
- If Vape WH continues returning zero product cards, run that scraper with a visible Firefox window so a human can complete any age, consent, or anti-bot prompt. A terminal bell can be emitted before waiting for manual interaction when unattended operation is not reliable.
- Do not repeatedly retry a 403 or challenge page headlessly. Preserve the browser page source for diagnosis and use a bounded manual-interaction wait instead.
- Vape WH currently uses WordPress/WooCommerce category and brand URLs such as `/product-category/all-disposable-e-cigs/` and `/brand/off-stamp/`, not the older Shopify-style `/collections/...` paths.
- The current listing cards use `.category-section-grid .products-section-card`. Product names are in `.products-section-card-description`, prices are in `.products-section-card-price .woocommerce-Price-amount`, and product links are available from `.products-section-card-image` or `.products-section-card-button`.
- When a product link is optional or has multiple selector fallbacks, assign the normalized URL and tag outside the successful-selector conditional. An unconditional print or fetch must never reference `full_link` or `tag` before assignment.

### My Vapor Store: Session Reuse and Category Flow

- My Vapor Store currently exposes Volusion category paths ending in numeric `.htm` identifiers, including the top-level megamenu paths `/New-Arrivals-Vape-s/77.htm`, `/Shop-by-Brand-s/194.htm`, `/E-Cig-Starter-Kits-E-Cigarette-s/70.htm`, `/Accessories-s/207.htm`, `/Dry-Herb-Oil-Wax-Vaporizer-s/621.htm`, and `/Vape-Clearance-Sale-s/398.htm`.
- Reuse one long-lived Firefox driver across category pages and product pages. This preserves the visible age/session state and avoids reopening the browser for every URL.
- Keep the page loop inside the category loop. A common silent failure is accidentally dedenting `while page` so only one category or one product is processed before advancing.
- Headed execution is the reliable mode for this site. The shared `HEADLESS` environment variable defaults to `0`; use `HEADLESS=1` only when a headless session has been verified.
- My Vapor Store cannot currently run headless reliably; always use `HEADLESS=0` for production runs.

### Vape.com: Browser Requirement

- Vape.com is a current Next.js storefront, not the old Shopify-style implementation.
- Its scraper uses rendered category pages and should run with a visible browser. It cannot currently run headless reliably; use `HEADLESS=0`.

### Vape.com and Perfect Vape Completion Notes

- `vaping.com`, `ecigmafia.com`, `vape.com`, and `perfectvape.com` have separate site entry points and should not be collapsed into one database site identity.
- Vape.com currently uses a Next.js storefront and current collection routes such as `/collections/new-arrivals`; the old `/products/disposables` routes are stale. Product links should be discovered from rendered pages, and `HEADLESS=0` is required for reliable operation.
- Vape.com image records belong under `data_from_sites_v2/VAPE.COM_images`; existing products should be backfilled only when `ecig_images` has no record.

### Vaping.com and ECigMafia

- Both current storefronts are BigCommerce Stencil sites and use the shared implementation in `scraping/bigcommerce_common.py` with site-specific entry points in `scraping/vaping.py` and `scraping/ecigmafia.py`.
- Their current product listings use BigCommerce `article.card` markup, but price placement varies by theme. Check data attributes, price containers, and the product-page `product:price:amount` metadata before treating a missing price as a parser failure.
- Their image galleries may expose `data-zoom-image`, `data-src`, `src`, or `srcset`; prefer the largest available source, deduplicate URLs, and save beneath the site-specific `data_from_sites_v2/<SITE>_images` directory.

### Site Category Normalization

- All scrapers should use `normalize_site_category()` from `scraping/ecig_parsing.py` when deriving `site_category`.
- The normalized value removes query strings, leading/trailing slashes, and URL prefixes such as `collections/`, `product-category/`, `category/`, `brand/`, and `pages/`.
- `.html` and `.htm` suffixes are removed, and nested paths are represented with hyphens. For example, `/collections/disposable-vapes/?page=2` becomes `disposable-vapes`.

### Existing Product Image Policy

- Before downloading images for an existing product, query `ecig_images` by `product_id`.
- If at least one image record exists, skip image fetching for that product and continue price/review updates.
- Only image-backfill a product when the database has zero image records. This avoids re-downloading every image on every run while still repairing products that were previously inserted without images.

### VaporFi: Shopware 6

- VaporFi is a Shopware 6 storefront. Product listing containers use `.cms-element-product-listing-wrapper[data-listing="true"]`, rows use `.cms-listing-row.js-listing-wrapper`, and cards use `.card.product-box[data-product-information]`.
- Card URLs and names are available from `a.product-image-link[href]` and `a.product-name`; card prices are in `.product-price`. The catalog reports a page size of 24 by default and uses the Shopware `p` query parameter for pagination.
- Product pages expose reliable Schema.org fields inside `.product-detail-buy`: `itemprop="name"`, `description`, `sku`, `brand`, `offers`, and `price`. Visible fallbacks are `h1.product-name`, `.brands a`, `.product-description`, and `.product-detail-price`.
- Product media is under `.product-detail-media`; prefer the largest `srcset` candidate and skip logos, placeholders, data URLs, and duplicate URLs.
- Variant values are in `form[data-variant-switch="true"]`, `.product-detail-configurator-option-label`, and `.product-detail-configurator-option-input`. Availability can vary by selected variant, so the back-in-stock form and delivery text are useful stock signals.
- Native reviews use `.product-detail-reviews` and `.product-review-point`; VaporFi also loads Reviews.io client-side. Do not invent review records when only the widget shell is present; use the shared fallback parser for server-rendered reviews and add a separate widget fetch only after live verification.
- The age gate is `#ageVerificationOverlay` with `#enterBtn`; it is commonly present but hidden after the session cookie is set. Check its rendered state rather than treating its DOM presence as a block.
- VaporFi category pages are large and navigation discovery can expose product URLs and informational routes. Keep only same-site catalog/category paths, exclude account/cart/blog/policy routes, and retain explicit category seeds as fallbacks.

## 18. Definition of Done

A new scraper is ready when:

- it runs from the repository root using the project virtual environment
- it has a site constant recognized by `db/db_azure.py`
- it discovers products across all intended categories with bounded pagination
- it canonicalizes URLs and creates stable tags
- it handles optional dialogs and JavaScript rendering without crashing
- it caches fetched pages and deduplicates products
- it stores raw HTML and plain text
- it populates the shared product data contract
- it downloads valid images beneath `BOX_DIR`
- it inserts new products through `map_product_data()`
- it updates existing prices and reviews without duplicating products
- it normalizes review fields and dates
- it logs failures with enough context to diagnose layout changes
- it passes `py_compile` and a small live sample run
- a second run is idempotent
