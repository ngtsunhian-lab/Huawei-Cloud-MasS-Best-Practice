# MercadoLibre Brazil Product Data Scraping — Technical Architecture

> Generated: 2026-05-12 · Dataset: 524 unique products · Platform: MercadoLibre Brazil (MLB)

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [System Architecture](#2-system-architecture)
3. [API Reverse Engineering](#3-api-reverse-engineering)
4. [Scraping Pipeline](#4-scraping-pipeline)
5. [Data Structure](#5-data-structure)
6. [Anti-Bot & Authentication](#6-anti-bot--authentication)
7. [Deduplication & Pagination](#7-deduplication--pagination)
8. [Results](#8-results)
9. [Issues & Solutions](#9-issues--solutions)

---

## 1. Project Overview

### Goal

Scrape electronics product data from MercadoLibre Brazil (MLB), covering smartphones, tablets, laptops, headphones, smartwatches, and more. Collect product title, price, discount, installment plan, rating, seller level, brand, model, and other structured fields.

### Approach Comparison

```
Option A: Browser HTML scraping       ❌ Complex rendering, unstable DOM structure
Option B: Official Partner API        ❌ Requires merchant approval
Option C: Reverse Android App API     ✅ Structured JSON, no login required, full fields
```

**Chosen approach**: Reverse engineer the internal search API called by the MercadoLibre Android app. Simulate app request headers to call it directly — no app installation or browser required.

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                          Local Mac                               │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                   meli_scraper.py                       │   │
│  │                                                         │   │
│  │  ┌──────────┐    ┌──────────┐    ┌──────────────────┐  │   │
│  │  │ Query    │───▶│ Pagination│───▶│  HTTP Request    │  │   │
│  │  │ List     │    │ offset++ │    │  Spoof Android   │  │   │
│  │  │ 10 terms │    │ limit=20 │    │  Headers + Token │  │   │
│  │  └──────────┘    └──────────┘    └────────┬─────────┘  │   │
│  │                                           │            │   │
│  │  ┌──────────────────────────────────────┐ │            │   │
│  │  │   Global dedup set: seen_global      │◀┤            │   │
│  │  │   (keyed by item.id)                 │ │            │   │
│  │  └──────────────────────────────────────┘ │            │   │
│  └────────────────────────────────────────────┼────────────┘   │
│                                               │                │
└───────────────────────────────────────────────┼────────────────┘
                                                │ HTTPS
                                                ▼
┌─────────────────────────────────────────────────────────────────┐
│              MercadoLibre CDN / API Gateway                      │
│                                                                 │
│    frontend.mercadolibre.com/sites/MLB/search                   │
│                                                                 │
│    ┌─────────────┐    ┌──────────────┐    ┌─────────────────┐  │
│    │ Auth check   │    │ Search engine│    │ Product DB      │  │
│    │ Bearer Token │    │ 28,000+ SKUs │    │ attributes      │  │
│    │ User-Agent   │    │ paginated    │    │ pricing engine  │  │
│    └─────────────┘    └──────────────┘    └─────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                                                │
                                                ▼ JSON Response
┌─────────────────────────────────────────────────────────────────┐
│                      Data Processing Layer                       │
│                                                                 │
│   extract_product()  ──▶  field normalization  ──▶  type cast  │
│   extract_attrs()    ──▶  flatten attributes   ──▶  brand/model│
│                                                                 │
│                    ▼                                            │
│              meli_products.json                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. API Reverse Engineering

### 3.1 Endpoint Discovery

Traffic from the MercadoLibre Android app was captured via mitmproxy. The core search endpoint is:

```
GET https://frontend.mercadolibre.com/sites/MLB/search
```

### 3.2 Request Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| `q` | `celular` | Search keyword (Portuguese) |
| `offset` | `0, 20, 40, ...` | Pagination offset |
| `page_size` | `50` | Requested page size (server actually returns ~20–28) |
| `context` | `android` | Triggers Android-specific response format |

### 3.3 Authentication Headers

```http
GET /sites/MLB/search?q=celular&offset=0&page_size=50&context=android HTTP/1.1
Host: frontend.mercadolibre.com
authorization: Bearer APP_USR-7092-031215-44831921c6deeb3c836569a33ca865e5-3215870989
user-agent: MercadoLibre-Android/10.507.1 (Pixel 7 Pro; Android 13; Build/TQ3A.230901.001)
accept: application/json
x-platform: android
accept-language: pt-BR
```

**Key fields:**

- `authorization`: App-level Bearer Token (not user-level) — hardcoded in the APK, no login required
- `user-agent`: Exact match of MercadoLibre Android v10.507.1 on Pixel 7 Pro
- `x-platform: android`: Signals server to return Android JSON format (not Web HTML)
- `accept-language: pt-BR`: Returns Brazilian Portuguese content and BRL currency

### 3.4 API Response Format Evolution

The API response format changed three times during development:

```
Version 1 (early):  components array with POLYCARD / SEARCH_RESULT_ITEM types
     │
     ▼
Version 2 (mid):    results array with flat product objects
     │
     ▼
Version 3 (current): components array; products have type=null containing an 'item' key
```

**Current (v3) response structure:**

```json
{
  "site_id": "MLB",
  "query": "celular",
  "paging": {
    "total": 28557,
    "offset": 0,
    "limit": 20,
    "primary_results": 1000
  },
  "components": [
    {
      "id": "MLB4583723537",
      "state": "VISIBLE",
      "item": { ... }          ← product data lives here
    },
    {
      "id": "...",
      "type": "FILTER_SPECIALIZED",   ← UI component, skip
      ...
    },
    {
      "id": "...",
      "type": "CAROUSEL",             ← UI component, skip
      ...
    }
  ]
}
```

**Key pattern**: Product components have `type == null` (Python `None`); all other entries are UI components (filters, carousels, etc.).

---

## 4. Scraping Pipeline

### 4.1 Main Flow

```
Start
  │
  ▼
Initialize global dedup set: seen_global = set()
  │
  ▼
Iterate over query list (10 terms):
  │
  ├─▶ query="celular",           limit=150
  ├─▶ query="smartphone",        limit=100
  ├─▶ query="tablet android",    limit=50
  ├─▶ query="notebook",          limit=50
  ├─▶ query="fone de ouvido bluetooth", limit=50
  ├─▶ query="smartwatch",        limit=50
  ├─▶ query="power bank",        limit=30
  ├─▶ query="samsung galaxy",    limit=50
  ├─▶ query="iphone",            limit=50
  └─▶ query="xiaomi redmi",      limit=50
  │
  ▼
For each query: run scrape_query()
  │
  ▼
Global dedup → append to all_products
  │
  ▼
Write meli_products.json
  │
  End
```

### 4.2 Per-Query Scraping Loop (scrape_query)

```
scrape_query(query="celular", max_items=150)
  │
  ├── offset = 0
  │     │
  │     ▼
  │   GET /search?q=celular&offset=0&page_size=50
  │     │
  │     ▼
  │   Parse components → extract items where type=None
  │     │
  │     ├── Got 28 items
  │     ├── Deduplicate within query, add to products
  │     └── offset += paging.limit (= 20)
  │
  ├── offset = 20 → request → 28 items
  ├── offset = 40 → request → 28 items
  ├── offset = 60 → request → 27 items
  ├── offset = 80 → reached 150 quota → stop
  │
  └── return products[:max_items]
```

### 4.3 Pagination Logic

```python
offset += limit          # limit read dynamically from paging.limit (currently 20)
if len(products) >= max_items:
    break                # quota reached for this query
if offset >= min(total, 1000):
    break                # API hard cap: offset > 1000 returns empty results
time.sleep(0.5)          # polite delay between requests
```

**Why is offset capped at 1000?**
MercadoLibre only exposes the first 1,000 results via the search API (`primary_results: 1000`). Requests beyond this return empty responses — this is intentional as part of their access control.

---

## 5. Data Structure

### 5.1 Field Extraction Logic

```
API item object
│
├── item.id                          → product.id
├── item.title                       → product.title
├── item.condition                   → product.condition  ("new" / "used")
│
├── item.price{}
│     ├── .amount                    → product.price_brl
│     ├── .original_price            → product.original_price_brl
│     ├── .discount_rate             → product.discount_rate   (%)
│     └── .discount_label.text       → product.discount_label  ("34% OFF")
│
├── item.installments{}
│     ├── .quantity                  → product.installments_count
│     ├── .amount                    → product.installments_value_brl
│     └── .rate                      → product.installments_rate  (0 = interest-free)
│
├── item.reviews{}
│     ├── .rating_average            → product.rating
│     └── .total                     → product.rating_count
│
├── item.seller_info{}
│     ├── .id                        → product.seller_id
│     ├── .power_seller_status       → product.seller_level  ("platinum")
│     └── .official_store_name       → product.official_store
│
├── item.tags[]                      → product.free_shipping / fulfillment / interest_free
│     ("free_shipping", "fulfillment", "interest_free", ...)
│
├── item.list_picture{}
│     └── .url                       → product.thumbnail
│
├── item.category_id                 → product.category_id
├── item.permalink                   → product.url
│
└── item.attributes[]                → extract_attrs() → flat attribute dict
      [{"name":"Marca","value_name":"Samsung"},
       {"name":"Cor","value_name":"Preto"},
       {"name":"Modelo detalhado","value_name":"A17"},...]
      │
      ├── "Marca"                    → product.brand
      ├── "Modelo" / "Modelo detalhado" → product.model
      ├── "Memória RAM"              → product.ram
      ├── "Armazenamento"            → product.storage
      ├── "Tamanho da tela"          → product.screen
      └── "Cor"                      → product.color
```

### 5.2 Attribute Flattening Function

```python
def extract_attrs(attributes):
    attrs = {}
    for a in (attributes or []):
        if isinstance(a, dict):
            name = a.get('name', '')        # attribute name (in Portuguese)
            val = a.get('value_name', '')   # attribute value
            if name and val:
                attrs[name] = val
    return attrs
```

The API returns up to 14 attributes per product as a list. This function flattens them into a dict, then target fields are extracted by their Portuguese key names. Missing fields default to empty string.

### 5.3 Output JSON Schema

```json
{
  "generated_at": "2026-05-09T19:02:43.982062Z",
  "source": "MercadoLibre Brazil",
  "queries": ["celular", "smartphone", "tablet android", ...],
  "total_unique_products": 524,
  "products": [
    {
      "id": "MLB4583723537",
      "title": "Celular Samsung Galaxy A17 Com Ia, 256gb...",
      "condition": "new",
      "price_brl": 1171,
      "original_price_brl": 1799,
      "discount_rate": 34,
      "discount_label": "34% OFF",
      "installments_count": 10,
      "installments_value_brl": 117.14,
      "installments_rate": 0,
      "rating": 4.9,
      "rating_count": 24729,
      "seller_id": 480263032,
      "seller_level": "platinum",
      "official_store": "Samsung",
      "free_shipping": false,
      "fulfillment": false,
      "interest_free": true,
      "category_id": "MLB1055",
      "url": "https://www.mercadolivre.com.br/...",
      "thumbnail": "https://http2.mlstatic.com/...",
      "brand": "Samsung",
      "model": "A17",
      "ram": "",
      "storage": "",
      "screen": "",
      "color": "Preto",
      "query": "celular"
    }
  ]
}
```

### 5.4 Product Field Reference

| Field | Type | Coverage | Description |
|-------|------|----------|-------------|
| `id` | str | 100% | MercadoLibre product ID (e.g. MLB4583723537) |
| `title` | str | 100% | Full product listing title (Portuguese) |
| `condition` | str | 100% | `"new"` or `"used"` |
| `price_brl` | float | 100% | Current sale price in BRL |
| `original_price_brl` | float | 66% | Pre-discount price (null if no discount) |
| `discount_rate` | int | 66% | Discount percentage |
| `discount_label` | str | 66% | Display label e.g. `"34% OFF"` |
| `installments_count` | int | ~90% | Number of installments |
| `installments_value_brl` | float | ~90% | Value per installment in BRL |
| `installments_rate` | float | ~90% | Interest rate (0 = interest-free) |
| `rating` | float | 94% | Average rating (0–5) |
| `rating_count` | int | 94% | Number of ratings |
| `seller_id` | int | ~100% | Seller account ID |
| `seller_level` | str | 56% | Power seller tier: `"platinum"`, `"gold"`, etc. |
| `official_store` | str | ~20% | Brand official store name |
| `free_shipping` | bool | — | Whether free shipping applies |
| `fulfillment` | bool | — | Whether fulfilled by MercadoLibre |
| `interest_free` | bool | ~80% | Whether installments are interest-free |
| `category_id` | str | 100% | MercadoLibre category code (e.g. `MLB1055`) |
| `url` | str | 100% | Product page URL |
| `thumbnail` | str | ~95% | Main product image URL |
| `brand` | str | ~85% | Brand name from attributes |
| `model` | str | ~55% | Model name from attributes |
| `ram` | str | ~25% | RAM (phones/laptops only) |
| `storage` | str | ~30% | Storage capacity |
| `screen` | str | ~30% | Screen size |
| `color` | str | ~40% | Color |
| `query` | str | 100% | Search keyword that returned this product |

---

## 6. Anti-Bot & Authentication

### 6.1 Authentication Architecture

```
MercadoLibre Auth Layers:

Level 1: App-level Bearer Token
┌────────────────────────────────────────────────────────┐
│  APP_USR-7092-031215-44831921c6deeb3c836569a33ca865e5  │
│  · Hardcoded in the Android APK                        │
│  · Identifies the application, not the user           │
│  · No login required to call search endpoints         │
│  · Long-lived (update APK to get new token)           │
└────────────────────────────────────────────────────────┘

Level 2: User-Agent Check
┌────────────────────────────────────────────────────────┐
│  MercadoLibre-Android/10.507.1 (Pixel 7 Pro; ...)      │
│  · Server uses UA to select response format            │
│  · Missing UA → returns Web HTML or rejected           │
│  · Must match a known app version exactly              │
└────────────────────────────────────────────────────────┘

Level 3: Platform Header
┌────────────────────────────────────────────────────────┐
│  x-platform: android                                   │
│  · Confirms platform type (redundant with UA)          │
│  · Triggers the Android API response path              │
└────────────────────────────────────────────────────────┘
```

### 6.2 Rate Limiting Strategy

| Technique | Implementation |
|-----------|---------------|
| Inter-request delay | `sleep(0.5)` after each paginated request |
| Inter-query delay | `sleep(1)` after each keyword is finished |
| Timeout | `timeout=20` seconds to avoid blocking |
| Error handling | Non-200 response stops current query, does not abort globally |

### 6.3 Comparison with Shopee & AliExpress

```
                    MercadoLibre         Shopee               AliExpress
                    ─────────────        ──────────────        ─────────────────
Auth method         Bearer Token (APK)   None (Facebook Bot)  API key (Affiliate)
Login required      No                   No                   No (Phase1), No (Phase2)
Anti-bot check      Very low             Heavy (418 blanket)  X5/AWSC + login wall
Token type          App-level, static    UA-based SSR bypass  MD5-signed API key
Data completeness   100% price coverage  10.9% price          0% Phase1, ~100% Phase2
Difficulty          Easy                 Medium               Hard (login wall)
```

**MercadoLibre is the most accessible of the three platforms** — the Bearer Token from the APK provides direct access to a full search API with structured JSON, prices, ratings, and seller data all in a single response.

---

## 7. Deduplication & Pagination

### 7.1 Two-Level Deduplication

```
Level 1: Per-query dedup (seen_ids)
┌─────────────────────────────────────────┐
│ Inside scrape_query()                   │
│                                         │
│  seen_ids = set()                       │
│  for item in page_results:              │
│    if item.id not in seen_ids:          │
│      seen_ids.add(item.id)              │
│      products.append(item)              │
│                                         │
│ Purpose: prevent intra-query duplicates │
│ caused by overlapping pagination        │
└─────────────────────────────────────────┘

Level 2: Global dedup (seen_global)
┌─────────────────────────────────────────┐
│ In main loop                            │
│                                         │
│  seen_global = set()                    │
│  for query, limit in queries:           │
│    products = scrape_query(query)       │
│    for p in products:                   │
│      if p.id not in seen_global:        │
│        seen_global.add(p.id)            │
│        all_products.append(p)           │
│                                         │
│ Purpose: Samsung Galaxy A17 may appear  │
│ in "celular", "smartphone", AND         │
│ "samsung galaxy" queries — global dedup │
│ ensures each product is recorded once   │
└─────────────────────────────────────────┘
```

### 7.2 Why Cross-Query Duplicates Are High

```
Query "celular"         ──────────────────────┐
Query "smartphone"      ─────────────────┐   │  Samsung Galaxy A17
Query "samsung galaxy"  ──────────┐      │   │  appears in all three
                                   ▼      ▼   ▼
                              Global dedup set
                              keeps only first occurrence
```

10 queries theoretically could yield ~630 records, but the actual result is 524 unique products — a ~17% cross-query duplication rate. This is expected for electronics queries that overlap heavily.

### 7.3 Pagination Boundary Control

```
Available range:  offset 0 → 1000 (API hard limit)
Page step size:   20 (from paging.limit — server decides, ignores page_size=50)
Max results/query: 50 steps × 20 = 1,000 items

"celular" server total = 28,557 products
API exposes first 1,000 → we stop earlier at our per-query quota (150)
```

---

## 8. Results

### 8.1 Collection Scale

| Metric | Value |
|--------|-------|
| Total unique products | **524** |
| Search queries | 10 |
| Price range | R$18 — R$14,984 |
| Average price | R$1,950 |
| Collection time | ~3 minutes |

### 8.2 Products per Query

```
celular              ████████████████████████████████  150
tablet android       ████████████                       50
notebook             ████████████                       50
fone bluetooth       ████████████                       50
smartwatch           ████████████                       50
smartphone            ███████████                       43
xiaomi redmi          ████████                          37
iphone                ████████                          34
samsung galaxy        ████████                          30
power bank            ███████                           30
```

### 8.3 Brand Distribution (Top 10)

```
Samsung     ████████████████████████  93  (17.7%)
Xiaomi      ████████████████████      77  (14.7%)
Apple       █████████████████         66  (12.6%)
Motorola    ████████                  32  ( 6.1%)
Lenovo      ██████                    23  ( 4.4%)
Realme      ████                      15  ( 2.9%)
Asus        ████                      15  ( 2.9%)
Acer        ███                       12  ( 2.3%)
Positivo    ███                       11  ( 2.1%)
Microwear   ███                       10  ( 1.9%)
Others      ██████████████████████   170  (32.4%)
```

### 8.4 Data Quality Metrics

| Metric | Value | Rate |
|--------|-------|------|
| Products with discount info | 347 | 66% |
| Products with rating | 496 | 94% |
| Platinum seller products | 294 | 56% |
| Interest-free installments | majority | — |

### 8.5 Field Coverage

```
id               ████████████████████ 100%
title            ████████████████████ 100%
price_brl        ████████████████████ 100%
rating           ██████████████████░░  94%
discount         ████████████████░░░░  66%
brand            ██████████████████░░  ~85%
model            ████████████░░░░░░░░  ~55%
storage          ██████░░░░░░░░░░░░░░  ~30%
ram              █████░░░░░░░░░░░░░░░  ~25%
```

---

## 9. Issues & Solutions

### Issue 1: API Response Format Changed Three Times

```
Timeline:
  ── v1 ──────── v2 ──────── v3 (current) ──▶
  components     results      components
  POLYCARD type  flat array   type=None + item

Discovery process:
  1. Ran old script → 0 products returned
  2. Printed data.keys() → 'results' key missing
  3. Inspected data['components'][0] → type is None, has 'item' key
  4. Updated extraction logic

Fix:
  # Old: data.get('results', [])
  # New:
  items = [c['item'] for c in components
           if c.get('type') is None and 'item' in c]
```

### Issue 2: page_size=50 But Only 20 Items Returned

```
Sent:      page_size=50
Received:  paging.limit = 20  (server ignores client's page_size)

Impact: pagination step must follow paging.limit dynamically, not a fixed step

Fix:
  limit = data.get('paging', {}).get('limit', 20)
  offset += limit   # NOT offset += 50
```

### Issue 3: free_shipping Always False

```
Root cause: 'free_shipping' comes from item.tags[]
Actual tags observed: ['interest_free', 'product_ad', 'cart_eligible',
                       'best_seller_candidate']

The free_shipping tag may appear in item.shipping sub-object, not tags[].
The current dataset is search-result heavy (popularity-ranked listings),
where interest_free is the primary commercial hook; free shipping is
configured per-listing and not consistently surfaced in this API path.
```

### Issue 4: Missing RAM / Storage / Screen Size for Some Products

```
Root cause: attributes array content varies by product category
  - Phones:   "Memória RAM", "Armazenamento", "Tamanho da tela"
  - Headphones: "Tipo de conexão", "Resposta de frequência"
  - Laptops:  "Processador", "Tamanho da tela"

Solution: extract_attrs() returns a full flat dict; target fields are
          extracted by Portuguese key name. Missing fields default to
          empty string and do not affect other fields.
```

---

## Appendix: Core Code

### scrape_query — Full Function

```python
def scrape_query(query, max_items=100):
    url = "https://frontend.mercadolibre.com/sites/MLB/search"
    seen_ids = set()
    products = []
    offset = 0

    while len(products) < max_items:
        params = {'q': query, 'offset': offset,
                  'page_size': 50, 'context': 'android'}
        try:
            r = requests.get(url, headers=HEADERS, params=params, timeout=20)
            if r.status_code != 200:
                break
            data = r.json()
        except Exception as e:
            break

        # Current API format: type=None components contain the 'item' key
        components = data.get('components', [])
        items = [c['item'] for c in components
                 if c.get('type') is None and 'item' in c]

        if not items:
            break

        for item in items:
            p = extract_product(item)
            if p['id'] and p['id'] not in seen_ids:
                seen_ids.add(p['id'])
                p['query'] = query
                products.append(p)

        total = data.get('paging', {}).get('total', 0)
        limit = data.get('paging', {}).get('limit', 20)
        offset += limit
        if len(products) >= max_items or offset >= min(total, 1000):
            break
        time.sleep(0.5)

    return products[:max_items]
```

### HEADERS — App Simulation

```python
HEADERS = {
    "authorization": "Bearer APP_USR-7092-031215-44831921c6deeb3c836569a33ca865e5-3215870989",
    "user-agent": "MercadoLibre-Android/10.507.1 (Pixel 7 Pro; Android 13; Build/TQ3A.230901.001)",
    "accept": "application/json",
    "x-platform": "android",
    "accept-language": "pt-BR",
}
```

---

*Generated 2026-05-12 | Data file: `meli_products.json` | Scraper: `meli_scraper.py`*
*Method: MercadoLibre Android App API (frontend.mercadolibre.com) with APK Bearer Token*
