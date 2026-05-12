# AliExpress Brazil Product Data Scraping — Technical Architecture

> Generated: 2026-05-12 · Dataset: 32,000 keywords (Phase 1 complete) · Platform: AliExpress Brazil

---

## Table of Contents

1. [Project Overview & Challenges](#1-project-overview--challenges)
2. [System Architecture](#2-system-architecture)
3. [Technical Research: Anti-Bot Analysis](#3-technical-research-anti-bot-analysis)
4. [Phase 1: seo-alphabet Keyword Harvest](#4-phase-1-seo-alphabet-keyword-harvest)
5. [Phase 2: Affiliate API Product Search](#5-phase-2-affiliate-api-product-search)
6. [Data Structure](#6-data-structure)
7. [Results](#7-results)
8. [Comparison with MercadoLibre & Shopee](#8-comparison-with-mercadolibre--shopee)

---

## 1. Project Overview & Challenges

### Goal

Scrape product data from AliExpress Brazil (`pt.aliexpress.com` / `aliexpress.com/bra`), collecting product names, prices, ratings, brands, and category taxonomy.

### Core Challenges

AliExpress enforces a multi-layer anti-bot defense:

```
Challenge Layers:

Layer 1: X5/AWSC JavaScript Challenge    ← Bot fingerprinting in every page
Layer 2: Login Wall (server-side)        ← ALL product pages require active session
Layer 3: Cookie Binding                  ← Session tokens (xman_t, _m_h5_tk) expire
                                            and are IP/device-bound
Layer 4: API Authentication              ← mtop H5 API requires time-based sign token
                                            (MD5 of _m_h5_tk & timestamp & key & data)
Layer 5: fn/ Endpoint Restriction        ← Most internal /fn/ routes return ~170-byte
                                            error response regardless of authentication
```

**Outcome:**
- X5/AWSC: partially bypassed by Yuzu browser (Android WebView) on ARMCloud phone
- Login wall: ALL product content pages require an authenticated session — no public path exists to product prices/ratings without login
- fn/ endpoints: Only `fn/seo-alphabet/index` is publicly accessible without auth
- **Breakthrough**: The `seo-alphabet` endpoint returns 32,000+ popular product keywords with category taxonomy — accessible directly from any server without browser sessions

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Research Infrastructure                              │
│                                                                             │
│  ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────────┐   │
│  │  ARMCloud Phone   │   │   ECS Server      │   │    Local Mac         │   │
│  │  PAD: ACP61H5FU6 │──▶│  101.44.196.235   │   │  aliexpress_         │   │
│  │  Android 13      │   │  mitmproxy 8080   │   │  scraper.py          │   │
│  │  Yuzu Browser    │   │  Traffic logging  │   │  affiliate API calls │   │
│  └──────────────────┘   └──────────────────┘   └──────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘

Phase 1 (keyword harvest):
  Mac ──sshpass SSH──▶ ECS ──curl──▶ aliexpress.com/fn/seo-alphabet/index
                                      (no auth, no JS challenge, 40 pages)

Phase 2 (product search — requires credentials):
  Mac ──HTTPS──▶ api-sg.aliexpress.com/sync (Affiliate API, MD5 signed)
```

---

## 3. Technical Research: Anti-Bot Analysis

### 3.1 Infrastructure Setup

All AliExpress traffic from the ARMCloud phone was proxied through ECS mitmproxy:

```
ARMCloud Phone (Android 13, Yuzu Browser)
  → Clash transparent proxy (iptables CLASH chain)
  → SOCKS5 127.0.0.1:57891
  → ECS 101.44.196.235:8080 (mitmproxy)
  → AliExpress servers
          ↓ simultaneously logged
  mitmproxy CA cert installed as system-trusted
  Log: /var/log/mitmproxy/flows-2026-05-11.jsonl (2,000+ entries)
```

Log file format (flat JSON, one record per request):
```json
{"url": "...", "method": "GET", "status_code": 200,
 "content_length": 45000, "request_headers": {...}, "response_headers": {...}}
```

### 3.2 Endpoint Status Matrix

Analysis of mitmproxy traffic captured from the Yuzu browser session:

```
❌ Blocked — Login Required (redirect to login page):
┌──────────────────────────────────────────────────────────────────────┐
│ GET  pt.aliexpress.com/                                               │
│ GET  pt.aliexpress.com/category/phones.html                          │
│ GET  pt.aliexpress.com/w/wholesale-celular.html                      │
│ GET  www.aliexpress.com/popular.html                                  │
│ ALL product detail pages                                              │
└──────────────────────────────────────────────────────────────────────┘

❌ Blocked — 170-byte error (fn/ internal routes):
┌──────────────────────────────────────────────────────────────────────┐
│ GET  www.aliexpress.com/fn/recommend-products/...                     │
│ GET  www.aliexpress.com/fn/category-tree/...                         │
│ GET  www.aliexpress.com/fn/deal-products/...                         │
│ [Most /fn/ routes return ~170-byte stub response]                    │
└──────────────────────────────────────────────────────────────────────┘

❌ Blocked — mtop H5 API restricted methods:
┌──────────────────────────────────────────────────────────────────────┐
│ POST acs.aliexpress.com/h5/mtop.aliexpress.search.page.do/1.0/       │
│      → "API not found" (method restricted to mobile app)             │
│ POST acs.aliexpress.com/h5/mtop.ae.category.recommend.products/1.0/  │
│      → "API not found"                                               │
└──────────────────────────────────────────────────────────────────────┘

✅ Accessible (no auth required):
┌──────────────────────────────────────────────────────────────────────┐
│ GET  www.aliexpress.com/fn/seo-alphabet/index                         │
│      ?channel=popular&pageNo=N&pageVersion=1d83f91d7b218221cecdf0e9548cad9a │
│      → 45KB JSON · 800 keywords per page · 40 pages · NO LOGIN NEEDED │
│                                                                      │
│ POST acs.aliexpress.com/h5/mtop.ae.cookie.render/1.0/               │
│      → Sets _m_h5_tk session token (utility endpoint, no products)  │
└──────────────────────────────────────────────────────────────────────┘
```

### 3.3 X5/AWSC JavaScript Challenge

```
X5 Bot Challenge:
  - Every AliExpress page embeds a fingerprinting JS challenge
  - Detects: headless Chrome, server-side rendering, automated navigation
  - Yuzu browser (Android WebView) passes X5 — returns real session cookies
  - Direct curl/requests fails X5 → gets challenge HTML, not product data

Login Wall (separate from X5):
  - Even after passing X5, ALL product content pages redirect to login
  - The login requirement is server-side — not bypassed by X5 workarounds
  - xman_t cookie captured from Yuzu browser is valid but page-session-bound
  - Attempting to replay xman_t from another IP/device → login redirect
```

### 3.4 mtop H5 API — Token System

The `acs.aliexpress.com/h5/{method}` endpoint system requires a time-based signature:

```
Step 1: Get _m_h5_tk token
  POST acs.aliexpress.com/h5/mtop.ae.cookie.render/1.0/
  → Response sets cookie: _m_h5_tk={40-char-token}_{timestamp}

Step 2: Compute sign for API calls
  token = cookie value split by '_': token_hash, ts
  sign  = MD5(f"{token_hash}&{timestamp}&{app_key}&{json.dumps(data)}")

Step 3: Call API
  POST acs.aliexpress.com/h5/{method}/1.0/
  ?appKey=12574478&t={timestamp}&sign={md5}&jsv=2.6.2

Result: Search/recommend methods → "API not found" (mobile-app restricted)
        Only utility methods (cookie render, static config) succeed
```

### 3.5 Cookies Captured from Yuzu Browser

```http
Cookie: xman_t=ReWmFUK9Kwo/0Kh+G0qHGkIqEROr5/j30C2BU/3vnJJoihivRvoT9n5kZnXctOs0
        cna=IBaHIl9Q4l0CAWUsxOs/sXOO
        aep_usuc_f=site=bra&c_tp=BRL&region=BR&b_locale=en_US&ae_u_p_s=2
        _m_h5_tk=4da88a9871219559cc93f706eb4d9875_1778400682766
```

These cookies are necessary but not sufficient — replaying them from a different IP returns login redirect. A valid AliExpress session bound to the phone's IP is required to access product pages.

---

## 4. Phase 1: seo-alphabet Keyword Harvest

### 4.1 Discovery

The `fn/seo-alphabet/index` endpoint is AliExpress's internal SEO crosslink system — it powers the keyword taxonomy shown on the AliExpress popular-searches page. It returns a paginated list of popular product search keywords organized by category.

**Key properties:**
- No authentication required
- No JavaScript challenge (accessible via plain curl/requests)
- Accessible from any server IP (verified on ECS 101.44.196.235)
- 40 pages × ~800 keywords = ~32,000 unique keywords
- Each keyword includes category classification and a wholesale search URL

### 4.2 Request Format

```http
GET /fn/seo-alphabet/index?channel=popular&pageNo=1&pageVersion=1d83f91d7b218221cecdf0e9548cad9a HTTP/1.1
Host: www.aliexpress.com
Accept: application/json, */*
Accept-Language: pt-BR,pt;q=0.9
Referer: https://www.aliexpress.com/
```

**No Cookie, User-Agent, or auth token required.**

### 4.3 Response Structure

```json
{
  "data": {
    "data": {
      "seo_crosslinks_B": {
        "fields": {
          "pageInfo": {
            "totalPage": 40,
            "totalNum": 60000,
            "pageNo": 1
          },
          "list": [
            {
              "category": "Consumer Electronics",
              "data": [
                {
                  "displayName": "xiaomi redmi note 13",
                  "url": "https://www.aliexpress.com/w/wholesale-xiaomi-redmi-note-13.html"
                },
                ...
              ]
            },
            {
              "category": "Cellphones & Telecommunications",
              "data": [...]
            }
          ]
        }
      }
    }
  }
}
```

### 4.4 ECS Direct Access (Why Not ARMCloud syncCmd)

Initial implementation routed requests through ARMCloud `syncCmd` (phone shell):
- `syncCmd` has a **~45KB output size limit** — response is truncated for seo-alphabet pages
- File-based approach (write to phone file, then `cat`) also returned empty output
- **Solution**: Run curl directly on ECS server via SSH — no output truncation, no phone proxy needed

```python
def fetch_seo_page_ecs(page_no):
    url = (f'https://www.aliexpress.com/fn/seo-alphabet/index'
           f'?channel=popular&pageNo={page_no}'
           f'&pageVersion=1d83f91d7b218221cecdf0e9548cad9a')
    cmd = (
        f"curl -s --max-time 30 "
        f"-H 'Accept: application/json, */*' "
        f"-H 'Accept-Language: pt-BR,pt;q=0.9' "
        f"-H 'Referer: https://www.aliexpress.com/' "
        f"'{url}'"
    )
    raw = ecs_run(cmd, timeout=45)  # SSH → ECS → AliExpress
    return json.loads(raw)
```

### 4.5 Keyword Extraction

```python
def extract_keywords_from_seo(data):
    block = next(iter(data['data']['data'].values()))
    for group in block['fields']['list']:
        cat = group.get('category', '')
        for entry in group.get('data', []):
            yield {
                'keyword': entry['displayName'],
                'category': cat,
                'search_url': entry['url'],  # wholesale URL: /w/wholesale-{keyword}.html
            }
```

---

## 5. Phase 2: Affiliate API Product Search

### 5.1 Overview

AliExpress offers a free Affiliate API that returns real product data with prices, ratings, and commission rates. No browser session required — uses MD5-signed API keys.

**Registration**: [portals.aliexpress.com](https://portals.aliexpress.com/) → Dashboard → Tools → API → Create App

### 5.2 Signature Algorithm

```python
def affiliate_sign(params, app_secret):
    # Sort all parameter keys alphabetically
    sign_str = app_secret
    for k in sorted(params.keys()):
        sign_str += k + str(params[k])
    sign_str += app_secret
    return hashlib.md5(sign_str.encode('utf-8')).hexdigest().upper()
```

Example: `app_secret + "app_key" + app_key_value + "keywords" + keyword_value + ... + app_secret`

### 5.3 Available Methods

```
aliexpress.affiliate.hotproduct.query   ← Top-selling products globally
aliexpress.affiliate.product.query      ← Search by keyword (use seo-alphabet keywords)
aliexpress.affiliate.featuredpromo.get  ← Promotion products
```

### 5.4 Hot Products Request

```python
params = {
    'method': 'aliexpress.affiliate.hotproduct.query',
    'app_key': AFFILIATE_APP_KEY,
    'sign_method': 'md5',
    'timestamp': str(int(time.time() * 1000)),
    'v': '2.0',
    'page_no': '1',
    'page_size': '50',
    'target_currency': 'BRL',
    'target_language': 'PT',
    'platform_type': 'APP',
    'ship_to_country': 'BR',
}
params['sign'] = affiliate_sign(params, AFFILIATE_APP_SECRET)
resp = requests.get('https://api-sg.aliexpress.com/sync', params=params)
```

### 5.5 Keyword Search Request

```python
params = {
    'method': 'aliexpress.affiliate.product.query',
    'keywords': 'celular',          # from seo-alphabet keyword list
    'page_no': '1',
    'page_size': '50',
    'sort': 'SALE_PRICE_ASC',
    'target_currency': 'BRL',
    'target_language': 'PT',
    'ship_to_country': 'BR',
    'fields': 'commission_rate,sale_price,original_price,discount,product_title,'
              'product_main_image_url,evaluate_rate,lastest_volume,category_id,'
              'product_url,shop_id,seller_id',
    # ... + app_key, timestamp, sign_method, v, sign
}
```

---

## 6. Data Structure

### 6.1 aliexpress_keywords.json

```json
{
  "generated_at": "2026-05-11T...",
  "source": "AliExpress Brazil - seo-alphabet crosslink data",
  "method": "ECS direct HTTP (no auth required)",
  "total_keywords": 32000,
  "categories": {
    "Consumer Electronics": ["xiaomi redmi note 13", "samsung galaxy s24", ...],
    "Automobiles & Motorcycles": [...],
    "..."
  },
  "all_keywords": [
    {
      "keyword": "xiaomi redmi note 13",
      "category": "Consumer Electronics",
      "search_url": "https://www.aliexpress.com/w/wholesale-xiaomi-redmi-note-13.html"
    },
    ...
  ]
}
```

### 6.2 aliexpress_products.json

```json
{
  "generated_at": "2026-05-12T...",
  "source": "AliExpress Brazil",
  "method": "Phase1: seo-alphabet keyword harvest via ECS; Phase2: Affiliate API",
  "keyword_taxonomy": {
    "total_keywords": 32000,
    "categories": {
      "Automobiles & Motorcycles": {"count": 4619, "sample": [...]},
      "Consumer Electronics": {"count": 2214, "sample": [...]},
      "..."
    }
  },
  "total_products": 0,
  "products": [
    {
      "title": "Xiaomi Redmi Note 13 Pro 5G ...",
      "price_brl": 899.99,
      "original_price_brl": 1299.00,
      "discount": "30%",
      "rating": "97",
      "sales": 5000,
      "category_id": "509",
      "image": "https://ae01.alicdn.com/...",
      "url": "https://www.aliexpress.com/item/...",
      "shop_id": "123456",
      "commission_rate": "4.00%"
    }
  ]
}
```

### 6.3 Product Schema (Phase 2 Affiliate API)

| Field | Type | Description |
|-------|------|-------------|
| `title` | str | Full product name (in PT if target_language=PT) |
| `price_brl` | float | Sale price in BRL |
| `original_price_brl` | float | Original price before discount |
| `discount` | str | Discount percentage, e.g. "30%" |
| `rating` | str | Satisfaction rate 0–100, e.g. "97" |
| `sales` | int | Recent sales volume |
| `category_id` | str | AliExpress internal category ID |
| `image` | str | Product main image URL |
| `url` | str | Product page URL |
| `shop_id` | str | Seller shop ID |
| `commission_rate` | str | Affiliate commission rate, e.g. "4.00%" |

---

## 7. Results

### 7.1 Phase 1 — Keyword Taxonomy

| Metric | Value |
|--------|-------|
| Total unique keywords | **32,000** |
| Total in AliExpress DB | ~60,000 (server-reported) |
| Pages fetched | 40 of 40 |
| Categories | **33** |
| Collection method | ECS SSH + direct curl |
| Auth required | None |

**Top categories by keyword count:**

| Category | Keywords |
|----------|----------|
| Automobiles & Motorcycles | 4,619 |
| Home & Garden | 3,674 |
| Toys & Hobbies | 2,642 |
| Consumer Electronics | 2,214 |
| Sports & Entertainment | 1,860 |
| Beauty & Health | 1,728 |
| Computer & Office | 1,494 |
| Jewelry & Accessories | 1,323 |
| Motorcycle Equipments & Parts | 1,204 |
| Painting Pens | 1,086 |
| Cellphones & Telecommunications | 1,027 |

### 7.2 Phase 2 — Affiliate API (pending credentials)

Phase 2 requires registering a free Affiliate API application at portals.aliexpress.com.
Once configured, the scraper can collect:

- Up to 50 products per keyword query
- 150 hot products per run (3 pages × 50)
- Full price, discount, rating, and commission data
- Product images and shop IDs

Using the 1,027 Cellphones & Telecommunications keywords from Phase 1 as search queries would yield thousands of product records with complete pricing data.

---

## 8. Comparison with MercadoLibre & Shopee

```
                    MercadoLibre          Shopee               AliExpress (this)
                    ─────────────         ──────────────        ──────────────────────
Data source          Mobile search API     Facebook Bot SSR      seo-alphabet + Affiliate
Endpoint             frontend.meli.com     shopee.com.br HTML    AliExpress fn/ + API
Authentication       Bearer token (APK)    None (Bot SSR)        Phase1: none; Phase2: API key
Anti-bot bypass      Static APK token      facebookexternalhit   seo-alphabet: no bot check;
                                           User-Agent            Affiliate API: signed keys
Response format      JSON                  HTML → ld+json        Phase1: JSON; Phase2: JSON
Price coverage       100%                  10.9% (224/2059)      0% Phase1; ~100% Phase2
Total products       524 (10 queries)      2,059 (~540 pages)    32,000 keywords; products need creds
Data richness        High: rating,         Medium: rating,       High: price, discount,
                     seller, brand,        brand (1/page)        rating, commission
                     model, storage
Category precision   High (keyword)        Medium (broad cat)    High (seo-alphabet categories)
Throughput           20–28 items/request   10–20 priced/page     50 products/keyword/request
```

**Key insight**: AliExpress is the only platform requiring credentials for product price data.
The seo-alphabet endpoint is the only publicly accessible data source — it provides excellent
keyword taxonomy but no product prices. The Affiliate API bridges this gap cleanly once registered.

---

## Appendix: Scraper Configuration

### aliexpress_scraper.py

```
Phase 1:
  ECS_HOST = '101.44.196.235'   ECS server for seo-alphabet fetch via SSH
  KEYWORDS_FILE = aliexpress_keywords.json   Cache file (re-fetch with force_refresh=True)

Phase 2 (fill in after registration):
  AFFILIATE_APP_KEY = ''
  AFFILIATE_APP_SECRET = ''
  AFFILIATE_API_URL = 'https://api-sg.aliexpress.com/sync'

Running:
  python3 aliexpress_scraper.py          # Phase 1 only (load from cache or re-fetch)
  AFFILIATE_APP_KEY=... python3 ...      # Phase 1 + 2
```

### seo-alphabet pageVersion

```
pageVersion=1d83f91d7b218221cecdf0e9548cad9a
```
This version string appears stable — it is the same across all 40 pages and was consistent
across multiple collection runs. If the endpoint stops returning data, check if this version
has rotated by inspecting a fresh browser request to `www.aliexpress.com/popular.html`.

---

*Generated 2026-05-12 | Data files: `aliexpress_keywords.json`, `aliexpress_products.json` | Scraper: `aliexpress_scraper.py`*
*Phase 1 method: ECS SSH + direct curl to seo-alphabet (no auth) | Phase 2: Affiliate API (portals.aliexpress.com)*
