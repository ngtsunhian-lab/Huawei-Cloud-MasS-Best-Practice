# Shopee Brazil Product Data Scraping — Technical Architecture

> Generated: 2026-05-09 · Dataset: 2,059 products (224 with price, 101 with rating) · Platform: Shopee Brazil

---

## Table of Contents

1. [Project Overview & Challenges](#1-project-overview--challenges)
2. [System Architecture](#2-system-architecture)
3. [Technical Research: API Exploration](#3-technical-research-api-exploration)
4. [Final Solution: Facebook Bot SSR + ld+json](#4-final-solution-facebook-bot-ssr--ldjson)
5. [Data Structure](#5-data-structure)
6. [Scraping Pipeline](#6-scraping-pipeline)
7. [Results](#7-results)
8. [Comparison with MercadoLibre](#8-comparison-with-mercadolibre)
9. [Shopee Anti-Bot Analysis](#9-shopee-anti-bot-analysis)

---

## 1. Project Overview & Challenges

### Goal

Scrape product data from Shopee Brazil's main shopping site (`shopee.com.br`), collecting product names, prices, ratings, brands, and other structured information.
**Requirement: use shopee.com.br main site data only — not the social video feed at sv.shopee.com.br.**

### Core Challenges

Shopee Brazil operates one of the most aggressive anti-scraping systems in the industry:

```
Challenge Layers:

Layer 1: API Authentication             ← JWT Token / Cookie required
Layer 2: Anti-Bot Encrypted Tokens      ← Regenerated per request, cannot be replayed
Layer 3: Device Fingerprint Binding     ← Tokens are bound to device ID
Layer 4: Server-Side Behavioral Check   ← Valid tokens still return 418
Layer 5: Proxy / MitM Detection         ← Intercepted traffic blocks content APIs
```

**Outcome: All standard product APIs are blocked (error 90309999 / 418 / 403).
The breakthrough was discovering that the `facebookexternalhit/1.1` User-Agent triggers
Shopee's SSR mode, returning structured `ld+json` data embedded in HTML.**

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Research Infrastructure                       │
│                                                                     │
│  ┌──────────────────┐   ┌──────────────────┐   ┌────────────────┐  │
│  │  ARMCloud Phone   │   │   ECS Server      │   │   Local Mac    │  │
│  │  PAD: ACP61H5FU6 │──▶│  mitmproxy 8080   │   │  Python script │  │
│  │  Android 13      │   │  101.44.196.235   │   │  scraper.py    │  │
│  │  Yuzu Browser    │   │  Traffic logging  │   │                │  │
│  └──────────────────┘   └──────────────────┘   └────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                                          │
                                  Facebook Bot UA (facebookexternalhit/1.1)
                                                          │
                                                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│               shopee.com.br (Main Shopping Site — SSR Mode)          │
│                                                                     │
│    GET /list/{Category}                                             │
│    GET /search?keyword=...                                          │
│    ├── Triggers server-side rendering (SSR) → full HTML response    │
│    └── HTML contains 5 ld+json structured data blocks              │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼ HTML (with embedded ld+json)
┌─────────────────────────────────────────────────────────────────────┐
│                        ld+json Extraction Layer                      │
│                                                                     │
│  Block 1: WebSite                   ← Site info (ignored)           │
│  Block 2: BreadcrumbList            ← Navigation (ignored)          │
│  Block 3: ItemList (no price)       ← Search result URLs (discovery)│
│  Block 4: Product (rating, no price)← Featured product → ratings_map│
│  Block 5: ItemList (with price)     ← Context products → all_products│
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                    /Users/jasonhuang/MELI/shoppe/shopee_products.json
```

---

## 3. Technical Research: API Exploration

### 3.1 Infrastructure Setup

Cloud phone controlled via ARMCloud API, with Clash transparent proxy + mitmproxy intercepting HTTPS traffic:

```
ARMCloud Phone → Clash transparent proxy (iptables CLASH chain)
               → SOCKS5 (mitmproxy:8080 on ECS 101.44.196.235)
               → Shopee servers
                     ↓ simultaneously logged
          mitmproxy CA certificate installed as system-trusted
          Log: /var/log/mitmproxy/flows-2026-05-09.jsonl (2,000+ entries)
```

Clash configuration highlights:
- Listeners: 52220 (redir), 57891 (SOCKS5)
- iptables CLASH chain redirects all TCP/UDP
- DIRECT exemptions for UIDs: 1000, 10018, 10063 (system processes)
- All other traffic → ECS 101.44.196.235:8080 SOCKS5

### 3.2 API Status Matrix

Analysis of 2,000+ mitmproxy flow records:

```
❌ 418 Anti-Bot Block (all content APIs, error 90309999):
┌──────────────────────────────────────────────────────────┐
│ POST /api/v4/native/homepage                              │
│ GET  /api/v4/search/search_page_common?keyword=celular    │
│ GET  /api/v4/recommend/recommend?bundle=category_landing  │
│      &catid=11 (Celulares e Smartphones)                  │
│ GET  /api/v4/pdp/get (product detail page)               │
│ POST /api/v4/cart/get                                     │
└──────────────────────────────────────────────────────────┘

❌ 403 Direct Reject:
┌──────────────────────────────────────────────────────────┐
│ GET /api/v4/search/search_items?keyword=celular           │
│ GET /api/v4/flash_sale/get_all_sessions                   │
│ GET /api/v4/item/get?itemid=...&shopid=...               │
└──────────────────────────────────────────────────────────┘

✅ 200 OK (utility APIs and Facebook Bot SSR):
┌──────────────────────────────────────────────────────────┐
│ GET shopee.com.br/list/Celular (facebookexternalhit UA)   │  ← BREAKTHROUGH
│ GET shopee.com.br/search?keyword=celular (facebook UA)    │
│ GET /api/v4/itemcard/set/elements                         │
│ GET /api/v4/account/basic/get_account_info               │
│ POST /api/v1/configs                                      │
└──────────────────────────────────────────────────────────┘
```

### 3.3 Key Finding: Endpoint-Level Blocking

The block is at the API endpoint level, independent of authentication state:

```python
# Test results: content APIs return 418 regardless of cookies
tests = [
    ('No cookies',          {}),                          # → 418
    ('SPC_F only',          {'Cookie': 'SPC_F=...'}),    # → 418
    ('Fresh random device', {'Cookie': 'SPC_DID=xxx'}),  # → 418
    ('Full phone cookies',  {'Cookie': '...SPC_U=...'}), # → 418
]
# Conclusion: Shopee enforces a blanket block on shopee.com.br content APIs.
# The Facebook Bot SSR path bypasses this by triggering a different rendering pipeline.
```

### 3.4 Browser Approach Limitations

Yuzu Browser (UID 10062) loading shopee.com.br/list/Celular:
- Returns 246 KB HTML, but it's a React CSR shell with no product content
- After 45 seconds, the JS made no successful product API calls
- Root cause: every product API called by the JS returns 418

**Conclusion**: Browser automation is ineffective against Shopee's anti-bot stack. Facebook Bot SSR is the only viable path.

---

## 4. Final Solution: Facebook Bot SSR + ld+json

### 4.1 Discovery

Social platforms like Facebook crawl shared links to generate link previews. Shopee must return full content for Open Graph / SEO compliance. When the `facebookexternalhit/1.1` User-Agent is used:

```
Chrome UA      → CSR shell (no product data)          ❌
Facebook Bot   → SSR HTML (with ld+json structured data)  ✅
Googlebot      → 403 Forbidden                        ❌
Twitterbot     → 403 Forbidden                        ❌
```

Shopee only grants SSR to the Facebook bot — likely because Facebook is a major referral traffic source that Shopee cannot afford to break.

### 4.2 Request Format

```http
GET /list/Celular HTTP/1.1
Host: shopee.com.br
User-Agent: facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)
Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8
Accept-Language: pt-BR,pt;q=0.9
Accept-Encoding: gzip, deflate, br
Connection: keep-alive
```

**No Cookie or encrypted token required.**

### 4.3 URL Patterns

```python
# Category listing page
https://shopee.com.br/list/{Category}
# With sort order
https://shopee.com.br/list/{Category}?sortBy=pop
https://shopee.com.br/list/{Category}?sortBy=price_asc
https://shopee.com.br/list/{Category}?sortBy=price_desc
https://shopee.com.br/list/{Category}?sortBy=new
# Page 2
https://shopee.com.br/list/{Category}?page=2
# Search
https://shopee.com.br/search?keyword=celular+samsung
```

---

## 5. Data Structure

### 5.1 ld+json Block Layout

Each shopee.com.br listing page contains five `<script type="application/ld+json">` blocks:

```
Block 1: {"@type": "WebSite"}              ← Site metadata (ignored)
Block 2: {"@type": "BreadcrumbList"}       ← Breadcrumb navigation (ignored)
Block 3: {"@type": "ItemList"}  (no price) ← Search result product URLs
Block 4: {"@type": "Product"}   (rating)   ← Featured product with aggregateRating
Block 5: {"@type": "ItemList"}  (priced)   ← Context products with prices
```

**Extraction strategy**:
- Block 3 → product ID discovery
- Block 4 → stored in `ratings_map` (item_id → rating data)
- Block 5 → stored in `all_products` (item_id → product with price)

### 5.2 Product URL Encoding

```
https://shopee.com.br/some-product-name-i.{shop_id}.{item_id}
                                              ↑          ↑
                                    regex: r'i\.(\d+)\.(\d+)'
```

### 5.3 Block 4 — Product Schema (rating source)

```json
{
  "@type": "Product",
  "@context": "https://schema.org",
  "name": "Smartphone Samsung Galaxy A35 5G ...",
  "url": "https://shopee.com.br/...-i.123456.789012",
  "image": "https://down-br.img.susercontent.com/file/...",
  "brand": {"@type": "Brand", "name": "Samsung"},
  "aggregateRating": {
    "@type": "AggregateRating",
    "ratingValue": "4.9",
    "ratingCount": "15234"
  }
}
```

### 5.4 Block 5 — ItemList Schema (price source)

```json
{
  "@type": "ItemList",
  "@context": "https://schema.org",
  "itemListElement": [
    {
      "@type": "ListItem",
      "position": 1,
      "name": "Smartphone Samsung Galaxy A35 5G ...",
      "url": "https://shopee.com.br/...-i.123456.789012",
      "price": "R$899,00",
      "image": "https://down-br.img.susercontent.com/file/..."
    }
  ]
}
```

### 5.5 Price Parsing

```python
def parse_price(price_str):
    # "R$899,00" → 899.0 (Brazilian number format: period = thousands, comma = decimal)
    clean = price_str.replace('R$', '').strip().replace('.', '').replace(',', '.')
    m = re.search(r'[\d.]+', clean)
    return float(m.group()) if m else None
```

### 5.6 Output Schema

| Field | Type | Source | Description |
|-------|------|--------|-------------|
| `item_id` | int | URL regex | Shopee product ID |
| `shop_id` | int | URL regex | Shopee shop ID |
| `name` | str | Block 4/5 | Full product name |
| `price_str` | str | Block 5 | Raw price string, e.g. "R$899,00" |
| `price_brl` | float | Block 5 | Price in BRL |
| `image` | str | Block 4/5 | Product image URL |
| `url` | str | Block 4/5 | Product page URL |
| `position` | int | Block 5 | Position in listing |
| `rating` | float | Block 4 | Rating score (0–5) |
| `rating_count` | str/int | Block 4 | Number of ratings |
| `brand` | str | Block 4 | Brand name |
| `source` | str | Internal | Source URL that yielded this product |

---

## 6. Scraping Pipeline

### 6.1 Seed URL Strategy (Breadth-First)

```python
def build_seed_urls():
    # Round 1: one default page per category (maximum diversity)
    for cat in CATEGORIES:        # 27 categories
        urls.append(f'/list/{cat}')

    # Round 2: search keywords
    for kw in SEARCH_KEYWORDS:    # 36 keywords
        urls.append(f'/search?keyword={kw}')

    # Round 3: sort order variants (breadth-first: one sort per category before repeating)
    for sort in ['?sortBy=pop', '?sortBy=price_asc', '?sortBy=price_desc', '?sortBy=new']:
        for cat in CATEGORIES:
            urls.append(f'/list/{cat}{sort}')

    # Round 4: page 2 (each category × each sort order)
    for cat in CATEGORIES:
        for sort in SORT_ORDERS:
            urls.append(f'/list/{cat}{sort}&page=2')

    # Round 5: search keyword page 2
    for kw in SEARCH_KEYWORDS:
        urls.append(f'/search?keyword={kw}&page=2')
```

**Why breadth-first?** Block 4 (the rated featured product) only has 1 product per page.
Visiting all sort variants of the same category in sequence repeats the same featured product.
Breadth-first ordering maximizes the number of distinct featured products seen before
any category is revisited, growing `ratings_map` faster.

### 6.2 Main Collection Loop

```
Initialize all_products = {}    # item_id → product dict
           ratings_map = {}     # item_id → {rating, rating_count, brand}
           visited_urls = set()
   │
   ▼
Iterate over seed_urls
   │
   ├── fetch_page(url) → HTML
   │
   ├── extract_from_html(html) → (products_list, featured_dict)
   │        │
   │        ├── Scan all ld+json blocks
   │        ├── ItemList blocks → products_list (priced and unpriced)
   │        └── Product block → featured_dict (with rating)
   │
   ├── If featured has rating → store in ratings_map[item_id]
   │
   ├── For each product in products_list:
   │        ├── Not seen → all_products[item_id] = product
   │        └── Already seen → if new entry has price and existing doesn't, merge price
   │
   └── sleep(0.35)

   ▼
Rating backfill: for each item_id in ratings_map
                 if item is in all_products and has no rating → write rating data

   ▼
Save shopee_products.json
```

### 6.3 Rate Limiting & Retries

```python
def fetch_page(url, retries=2):
    for attempt in range(retries + 1):
        try:
            r = session.get(url, timeout=20, allow_redirects=True)
            if r.status_code == 200:
                return r.text
            elif r.status_code == 429:
                time.sleep(15)   # back off 15s on rate limit
            return None
        except Exception:
            if attempt < retries:
                time.sleep(2)    # 2s retry delay on network error
    return None

# Inter-request delay
time.sleep(0.35)  # 350 ms between pages
```

---

## 7. Results

### 7.1 Collection Scale

| Metric | Value |
|--------|-------|
| Total unique products | **2,059** |
| Products with price | **224** (10.9%) |
| Products with rating | **101** (4.9%) |
| Categories crawled | 27 |
| Search keywords | 36 |
| Total seed URLs | ~540 |
| Price range | R$1.97 — R$4,079.00 |
| Average price | R$218.72 |

### 7.2 Field Coverage

| Field | Coverage | Notes |
|-------|----------|-------|
| name | ~100% | Present in all Block 3/5 items |
| url | ~100% | URL encodes shop_id + item_id |
| image | ~95% | Occasional missing image |
| price_brl | 10.9% (224/2059) | Only Block 5 carries prices |
| rating | 4.9% (101/2059) | Only Block 4 carries ratings |
| brand | 4.9% (101/2059) | Same source as rating (Block 4) |

**Why is price coverage low?**
- Block 3 (discovery ItemList) contributes many item_ids but no prices
- Block 5 (priced ItemList) yields only ~10–20 products per page
- Block 4 (rated Product) yields only 1 featured product per page
- Product detail pages visited with Facebook Bot UA return only WebSite + BreadcrumbList blocks — no product data

### 7.3 Price Distribution

```
R$0–50        ████████               ~15 products
R$50–100      ████████████████       ~45 products
R$100–200     ████████████████████   ~60 products
R$200–500     ████████████           ~65 products
R$500–1000    ████████               ~25 products
R$1000+       ████████               ~14 products
```

---

## 8. Comparison with MercadoLibre

```
                    MercadoLibre                   Shopee (this approach)
                    ────────────────               ──────────────────────────
Data source          Product search API (direct)    Facebook Bot SSR ld+json
Endpoint             frontend.mercadolibre.com      shopee.com.br (HTML)
Authentication       Bearer token (from APK)        None required
Anti-bot token       Not required                   Not required (Bot SSR exempt)
Response format      JSON                           HTML → ld+json parse
Price coverage       100% (524/524)                 10.9% (224/2059)
Rating coverage      ~80%                           4.9% (101/2059)
Total products       524 (10 search queries)        2,059 (27 categories + 36 keywords)
Products with price  524                            224
Data richness        Rating, seller level,          Rating, brand
                     brand, model, storage          (featured products only)
Category precision   High (keyword search)          Medium (broad categories)
Throughput           20–28 products/request         10–20 priced products/page
```

**Core difference**: MercadoLibre's mobile search API is accessible with a static Bearer token from the APK.
Shopee enforces a blanket block on all product content APIs; the Facebook Bot SSR path is the only viable route to structured product data from the main shopping site.

---

## 9. Shopee Anti-Bot Analysis

### 9.1 Encrypted Token Stack

Headers observed in mitmproxy captures from the real Shopee app:

```http
# Per-request encrypted tokens (regenerated each call)
af-ac-enc-sz-token: qsDsbaI02HwkVSej8bB/aQ==|QtIsGcr+Pi03...  ← Primary anti-bot token
sfid:               8fW0FooEgL+SHMgy1ZnGVg==|RdIsGcr+Pi03...  ← Session fingerprint
x-sap-ri:           e53fff6982d7bc0d371a711a01f3927e73e9dc...  ← Request integrity signature
fb97709:            YrT4A0l/2HLy5j8YuVzYD8Rdxb8=              ← Device-bound signature
832dfed5:           tU/ei0De9pRgXlZT2G7oPyQo7/B=              ← Timestamp-bound token

# Generated in real time by Shopee's security SDK — cannot be reproduced by reverse engineering
```

### 9.2 Blocking Dimensions

```
Dimension 1: IP
  · Data center IPs → likely blocked outright

Dimension 2: Token
  · No encrypted token → 403 (direct reject)
  · Forged token → 418 (anomaly detected, error 90309999)
  · Legitimate token from real device → 418 (endpoint-level blanket block)

Dimension 3: Behavior
  · High request frequency → rate limiting or block

Dimension 4: User-Agent (key finding)
  · Standard Chrome UA → CSR shell, no product data
  · Googlebot → 403
  · Twitterbot → 403
  · facebookexternalhit/1.1 → SSR HTML with ld+json ✅
```

### 9.3 Why Does the Facebook Bot UA Work?

```
Hypothesis:
  1. Shopee depends on Facebook for referral traffic — broken link previews would
     directly hurt conversion, so they cannot block the Facebook crawler.
  2. Open Graph / Schema.org compliance is required for link cards on Facebook/WhatsApp.
  3. Facebook crawls are single-page, low-frequency, and legitimate —
     Shopee has no business reason to block them.

Limitations of this approach:
  · Only 1 rated featured product per listing page (Block 4)
  · Only ~10–20 priced context products per listing page (Block 5)
  · Product detail pages with Facebook Bot UA return no product data
  · Cannot enumerate all products — discovery is indirect via category/search pages only
```

---

## Appendix: Core Code

### extract_from_html

```python
def extract_from_html(html, source_url=''):
    """Returns (products list, featured product dict or None)."""
    products = []
    featured = None

    ld_blocks = re.findall(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        html, re.DOTALL
    )

    for block in ld_blocks:
        try:
            d = json.loads(block)
            dtype = d.get('@type', '')

            if dtype == 'ItemList':
                items = d.get('itemListElement', [])
                has_price = any(item.get('price') for item in items)
                for item in items:
                    url = item.get('url', '') or ''
                    m = re.search(r'i\.(\d+)\.(\d+)', url)
                    if not m:
                        continue
                    shop_id, item_id = int(m.group(1)), int(m.group(2))
                    products.append({
                        'item_id': item_id, 'shop_id': shop_id,
                        'name': item.get('name', ''),
                        'price_str': item.get('price', ''),
                        'price_brl': parse_price(item.get('price', '')),
                        'image': item.get('image', ''),
                        'url': url, 'position': item.get('position', 0),
                        'source': source_url, '_has_price_block': has_price,
                    })

            elif dtype == 'Product':
                url = d.get('url', '')
                m = re.search(r'i\.(\d+)\.(\d+)', url)
                if m:
                    rating_info = d.get('aggregateRating', {}) or {}
                    brand = d.get('brand', {})
                    featured = {
                        'item_id': int(m.group(2)), 'shop_id': int(m.group(1)),
                        'rating': rating_info.get('ratingValue') if isinstance(rating_info, dict) else None,
                        'rating_count': (rating_info.get('ratingCount') or rating_info.get('reviewCount')) if isinstance(rating_info, dict) else None,
                        'brand': brand.get('name', '') if isinstance(brand, dict) else '',
                        'name': d.get('name', ''), 'image': d.get('image', ''), 'url': url,
                    }
        except Exception:
            pass

    return products, featured
```

### Rating Backfill

```python
# During Phase 1: store ratings from featured product (Block 4)
if featured and featured.get('rating'):
    ratings_map[featured['item_id']] = {
        'rating': featured['rating'],
        'rating_count': featured['rating_count'],
        'brand': featured.get('brand', ''),
    }

# After Phase 1: backfill ratings into all_products
for iid, rdata in ratings_map.items():
    if iid in all_products and not all_products[iid].get('rating'):
        all_products[iid]['rating'] = rdata['rating']
        all_products[iid]['rating_count'] = rdata['rating_count']
        all_products[iid]['brand'] = rdata.get('brand', '')
```

---

*Generated 2026-05-09 | Data file: `shopee_products.json` | Scraper: `shopee_scraper.py`*
*Method: shopee.com.br SSR via facebookexternalhit/1.1 User-Agent + ld+json structured data extraction*
