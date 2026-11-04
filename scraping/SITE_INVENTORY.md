# Site Inventory

This inventory tracks retailer candidates and scraper status. A site marked
`not started` has not been added to the production scrape run. Access notes are
based on the latest repository or live-page check and should be revalidated
before production scheduling.

## Status Definitions

- `done`: scraper has been implemented and validated for the current site behavior.
- `active`: scraper exists and is included in the supported production flow.
- `in development`: scraper exists but is not production verified.
- `deferred`: known site, but access, scope, or reliability needs work first.
- `historical`: repository or database references exist, but no current active scraper is present.
- `closed`: site is known to be closed or out of business.
- `not started`: candidate has no scraper in this repository yet.
- `exclude`: not a retailer target for the current catalog scope.

## Production Scrapers

These scrapers are currently invoked by `run_scrape.sh` and are the completed
production set:

| Site | Script | Status |
| --- | --- | --- |
| Get Pop | `scraping/getpop.py` | done |
| Mi-Pod | `scraping/mipod.py` | done |
| Vape Sourcing | `scraping/vapesourcing.py` | done |
| Vape WH | `scraping/vapewh.py` | done |
| Huff and Puffers | `scraping/huffandpuffers.py` | done |
| My Vapor Store | `scraping/myvaporstore.py` | done |
| ECigMafia | `scraping/ecigmafia.py` | done |
| Vaping.com | `scraping/vaping.py` | done |
| Vape.com | `scraping/vape_com.py` | done |
| Perfect Vape | `scraping/perfectvape.py` | done |
| Puffco | `scraping/puffco.py` | done |
| Vapor DNA | `scraping/vapordna.py` | active |
| Prilla | `scraping/prilla.py` | active |
| Nicokick | `scraping/nicokick.py` | active |
| Northerner | `scraping/northerner.py` | active |
| ALP Pouch | `scraping/alp_pouch.py` | active |
| Sesh Products | `scraping/sesh_products.py` | active |
| Outlaw Dip | `scraping/outlaw_dip.py` | active |
| Spree Bar Sales | `scraping/spree_bar_sales.py` | active |
| West Coast Vape Supply | `scraping/west_coast_vape_supply.py` | active |
| Nic Pouches USA | `scraping/nic_pouches_us.py` | active |

Element Vape is not in `run_scrape.sh` because it currently requires separate
supervised access handling. GoPuff remains under `scraping/in_development/`.

## Existing Scrapers

| Site | Domain | Status | Platform / Notes |
| --- | --- | --- | --- |
| Get Pop | `getpop.co` | done | BigCommerce. Current paths use `/disposables/`, `/e-liquids/`, `/pod-systems/`, `/devices/`, `/pods/`, and `/nicotine-pouches/`. |
| Mi-Pod | `mipod.com` | done | BigCommerce. Uses `/collections/...`; age gate and `BCData` identifiers are handled. |
| My Vapor Store | `myvaporstore.com` | done | Volusion/custom storefront. Cannot run headless reliably; use `HEADLESS=0`. One browser session is reused and image backfill is supported. |
| Vape Sourcing | `vapesourcing.com` | done | Custom storefront with `.html` category paths. Current listings use `li.product-item`; image backfill is supported. |
| Vape WH | `vapewh.com` | done | WordPress/WooCommerce. Current paths use `/product-category/...` and `/brand/...`; headed mode may be needed for access prompts. Image backfill is supported. |
| Element Vape | `elementvape.com` | active | Security challenge/age-gate risk. Scraper includes challenge detection and a visible-browser wait. |
| Puffco | `puffco.com` | done | Shopify storefront. Primarily cannabis hardware; keep separate from nicotine-retailer priority. |
| GoPuff | `gopuff.com` | in development | Scraper is under `scraping/in_development/gopuff.py`. Location, age/account state, and access challenges remain unverified. |
| VaporFi | `vaporfi.com` | done | Shopware 6; server-rendered product listings with Shopware pagination, Schema.org product metadata, variant configurators, and a normally hidden age gate. Dedicated scraper is `scraping/vaporfi.py`; live one-product validation completed. |
| Huff and Puffers | `huffandpuffers.com` | done | WooCommerce Store API; dedicated scraper is `scraping/huffandpuffers.py`. Uses conservative API pagination, successful-response caching, block detection, Azure SQL writes, and AVIF-compatible image downloads. |
| Prilla | `prilla.com` | active | USA Magento storefront; dedicated scraper is `scraping/prilla.py`. Uses server-rendered category pages, sitemap discovery, product JSON-LD, lazy-loaded images, and review markup. |
| Nicokick | `nicokick.com` | active | USA Magento/Hyva storefront; dedicated scraper is `scraping/nicokick.py`. Uses server-rendered product cards, category sitemap discovery, product JSON-LD, and lazy-loaded images. |
| Northerner | `northerner.com` | active | USA Magento/Hyva storefront; dedicated scraper is `scraping/northerner.py`. Uses server-rendered product cards, category sitemap discovery, product JSON-LD, and lazy-loaded images. |
| ALP Pouch | `alppouch.com` | active | Shopify storefront; dedicated scraper is `scraping/alp_pouch.py`. Uses the public collection JSON endpoint and product pages, filtering to nicotine and caffeine pouch products. |
| Sesh Products | `seshproducts.com` | active | Shopify storefront; dedicated scraper is `scraping/sesh_products.py`. Uses the public nicotine-pouches collection JSON endpoint and filters out cans, apparel, bundles, and equipment. |
| Juice Head | `juicehead.com` | active | Shopify storefront; dedicated scraper is `scraping/juice_head.py`. Uses the public nicotine-pouches collection JSON endpoint and keeps individual nicotine-pouch cans while excluding bundles and accessories. |
| Outlaw Dip | `outlawdip.com` | active | Shopify storefront; dedicated scraper is `scraping/outlaw_dip.py`. Uses the public catalog JSON endpoint because the pouches collection JSON is empty, filtering to Reloads and Berserker pouch products while excluding dip, apparel, and other accessories. |
| Spree Bar Sales | `spreebarsales.com` | active | WooCommerce Store API; dedicated scraper is `scraping/spree_bar_sales.py`. Captures consumer flavor pods and starter kits, excludes batteries/accessories, and parses Metatine, puff, liquid, battery, flavor, image, stock, and price data. |
| West Coast Vape Supply | `westcoastvapesupply.com` | active | BigCommerce Stencil storefront; dedicated scraper is `scraping/west_coast_vape_supply.py`. Uses the public paginated `/shop-all/` catalog and follows the retailer's requested 10-second automated crawl delay. |
| Nic Pouches USA | `nicpouches.us` | active | Shopify storefront; dedicated scraper is `scraping/nic_pouches_us.py`. Uses the public catalog JSON endpoint, captures nicotine-pouch products and variants, and excludes samplers, bundles, and merchandise. |
| CSVape | `csvape.com` | closed | Site/store was reported closed; excluded from `run_scrape.sh`. |

### Access And Regional Updates

- `elementvape.com`: currently blocked during live access checks. Keep the scraper out of unattended production until access is restored or an approved access method is available.
- `gopuff.com`: currently blocked during live access checks. The scraper remains in `scraping/in_development/` and should not be added to the normal production run.
- `oozelife.com`: blocked by the project ISP. Mark as deferred unless network access changes or an approved data source becomes available.
- `vaporesso.com`: observed storefront/content appears Hungarian rather than USA-focused. Exclude from the USA retailer inventory unless a verified USA storefront or catalog endpoint is identified.

## Historical Or Aliased Sites

| Site | Domain | Status | Notes |
| --- | --- | --- | --- |
| Vape.com | `vape.com` | done | Current Next.js storefront; scraper is `scraping/vape_com.py`. Cannot run headless reliably; use `HEADLESS=0`. Separate retailer from `vaping.com`. Images and category normalization verified. |
| Perfect Vape | `perfectvape.com` | done | Current BigCommerce storefront; scraper is `scraping/perfectvape.py`. |

## Candidate Retailers

| Site | Domain | Status | Initial Notes |
| --- | --- | --- | --- |
| JUUL | `juul.com` | exclude | Manufacturer/brand site with age-gated/account-oriented access, not a broad independent retailer catalog. |
| Vapor DNA | `vapordna.com` | active | Shopify; uses collection and product JSON endpoints. |
| Vaping360 | `vaping360.com` | exclude | Media, product information, and deals portal rather than a conventional retailer catalog. |
| VaporFi | `vaporfi.com` | done | Shopware 6; USA-facing catalog validated with live category and product pages. Scraper is `scraping/vaporfi.py`. |
| Vape Juice Depot | `vapejuicedepot.com` | not started | E-liquid-focused retailer candidate. |
| Eight Vape | `eightvape.com` | not started | Retailer candidate; platform and access need validation. |
| Ejuice Connect | `ejuiceconnect.com` | not started | E-liquid-focused retailer candidate. |
| Smoke Day | `smokeday.com` | not started | Retailer candidate; platform and access need validation. |
| Juicefly | `juicefly.com` | not started | E-liquid/vape retailer candidate. |
| Flawless Vape Shop | `flawlessvapeshop.com` | not started | Retailer candidate; platform and access need validation. |
| Electric Tobacconist | `electrictobacconist.com` | not started | Retailer candidate; likely regional/access restrictions need validation. |
| Ejuice Direct | `ejuicedirect.com` | not started | E-liquid-focused retailer candidate. |
| Red Star Vapor | `redstarvapor.com` | not started | Retailer candidate; platform and access need validation. |
| Vapor Empire | `vaporempire.com` | not started | Retailer candidate; platform and access need validation. |
| Vapor Beast | `vaporbeast.com` | not started | Retailer candidate; platform and access need validation. |
| Breazy | `breazy.com` | not started | Retailer candidate; platform and access need validation. |
| Discount Vape Pen | `discountvapepen.com` | not started | Retailer candidate; platform and access need validation. |
| Ejuice Store | `ejuicestore.com` | not started | E-liquid-focused retailer candidate. |
| EC Blend Flavor | `ecblendflavors.com` | not started | E-liquid-focused retailer candidate; exact canonical domain needs validation. |
| Ejuice DB | `ejuicedb.com` | exclude | Product/review database rather than a conventional retailer catalog. |
| Lighter USA | `lighterusa.com` | not started | Retailer candidate; likely broader tobacco/accessory catalog. |
| Giant Vapes | `giantvapes.com` | not started | E-liquid-focused retailer candidate. |
| The Vapor Shoppe DNA | `thevaporshoppedna.com` | not started | Retailer candidate; exact canonical domain needs validation. |
| Mist Hub | `misthub.com` | not started | Retailer candidate; platform and access need validation. |
| Vape Society Supply | `vapesocietysupply.com` | not started | Retailer candidate; platform and access need validation. |
| Ejuices.com | `ejuices.com` | not started | E-liquid-focused retailer candidate. |
| Dash Vapes | `dashvapes.com` | not started | Retailer candidate; regional access and platform need validation. |
| Vape Shack | `vapeshack.com` | not started | Retailer candidate; platform and access need validation. |
| Vapezilla | `vapezilla.com` | not started | Retailer candidate; platform and access need validation. |
| Vape Dojo | `vapedojo.com` | not started | Retailer candidate; platform and access need validation. |
| Huff Vape | `huffvape.com` | not started | Retailer candidate; exact canonical domain needs validation. |
| EZ Puff | `ezpuff.com` | not started | Retailer candidate; platform and access need validation. |
| The Vape Mall | `thevapemall.com` | not started | Retailer candidate; platform and access need validation. |
| Xhale City | `xhalecity.com` | not started | Retailer candidate; platform and access need validation. |
| Black Note | `blacknote.com` | not started | E-liquid-focused brand/retailer candidate; scope needs validation. |
| Vape Street | `vapestreet.com` | not started | Retailer candidate; exact canonical domain needs validation. |
| Vape Craft Inc. | `vapecraftinc.com` | not started | Retailer candidate; exact canonical domain needs validation. |
| Vapor Puffs | `vaporpuffs.com` | not started | Retailer candidate; platform and access need validation. |
| Price Point NY | `pricepointny.com` | not started | Retailer candidate; regional access and platform need validation. |
| Vapor Boss | `vaporboss.com` | not started | Retailer candidate; platform and access need validation. |
| Vape Beat | `vapebeat.com` | not started | Retailer candidate; exact canonical domain needs validation. |
| Select Vape | `selectvape.com` | not started | Retailer candidate; platform and access need validation. |
| Beyond Vape | `beyondvape.com` | not started | Retailer/brand candidate; current catalog and domain need validation. |
| Vape Royalty | `vaperoyalty.com` | not started | Retailer candidate; platform and access need validation. |
| Ooze Life | `oozelife.com` | deferred | Blocked by the project ISP. Requires a verified USA-accessible route before investigation. |
| Vaporesso | `vaporesso.com` | exclude | Observed storefront appears Hungarian; outside the USA-only scope unless a USA catalog is confirmed. |

## Next-Batch Pilot

| Site | Domain | Status | Implementation |
| --- | --- | --- | --- |
| Vapor DNA | `vapordna.com` | active | Shopify storefront; dedicated implementation in `scraping/vapordna.py`. |
| EightVape | `eightvape.com` | not started | WooCommerce/WordPress storefront; needs a dedicated implementation. |

## Recommended Next Batch

Prioritize new scraper work by likely catalog value and accessible markup:

1. `vapordna.com`: Shopify with a broad USA-facing vape catalog.
2. `perfectvape.com`: BigCommerce and currently accessible; restore and verify the historical scraper.
3. `eightvape.com`: Large WooCommerce retailer candidate; validate category and product selectors before implementation.
4. `vaporauthority.com`: Broad disposables, e-liquid, pods, hardware, and nicotine-pouch catalog.
5. `vapor4life.com`: Established USA vape retailer with e-liquid, pods, and replacement products.
6. `nicokick.com`: Strong USA nicotine-pouch catalog with a clear age-gated product experience.
7. `smokingpipes.com`: Established USA online tobacco retailer for pipe tobacco, cigars, and accessories.

Run security-challenged or region-restricted sites separately from the normal
production batch. Do not add a candidate to `run_scrape.sh` until one category
and one product page have been validated against the database contract.
