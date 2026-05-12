# Brazil E-Commerce Scrapers

Three scrapers for Brazil's major e-commerce platforms, built to collect product data (titles, prices, ratings, brands) for market research.

| Platform | Method | Auth Required | Products |
|----------|--------|---------------|----------|
| [MercadoLibre](./mercado_libre/) | Android App API (Bearer Token from APK) | No | 524 |
| [Shopee](./shopee/) | Facebook Bot SSR + ld+json | No | 2,059 |
| [AliExpress](./aliexpress/) | seo-alphabet keywords + Affiliate API | Phase 2 only | 32,000 keywords |

## Structure

```
scraper/
├── mercado_libre/
│   ├── meli_scraper.py                  # Scraper (frontend.mercadolibre.com)
│   ├── meli_products.json               # 524 products with prices & ratings
│   ├── meli_scraper_architecture.md     # Architecture doc (Chinese)
│   └── meli_scraper_architecture_en.md  # Architecture doc (English)
│
├── shopee/
│   ├── shopee_scraper.py                # Scraper (facebookexternalhit UA)
│   ├── shopee_products.json             # 2,059 products
│   ├── shopee_architecture.md           # Architecture doc (Chinese)
│   └── shopee_architecture_en.md        # Architecture doc (English)
│
└── aliexpress/
    ├── aliexpress_scraper.py            # Scraper (ECS SSH + Affiliate API)
    ├── aliexpress_keywords.json         # 32,000 popular keywords × 33 categories
    ├── aliexpress_products.json         # Products (Phase 2 requires Affiliate API key)
    ├── aliexpress_architecture.md       # Architecture doc (Chinese)
    └── aliexpress_architecture_en.md    # Architecture doc (English)
```

## Key Findings

- **MercadoLibre**: Easiest — APK-embedded Bearer Token gives direct access to a full JSON search API. No login, no bot check. 100% price coverage.
- **Shopee**: `facebookexternalhit/1.1` User-Agent bypasses all anti-bot layers and triggers SSR mode with structured `ld+json` data. All content APIs return 418 with any other UA.
- **AliExpress**: Hardest — login wall blocks all product pages server-side. The `fn/seo-alphabet/index` endpoint is the only public data source (keywords only, no prices). Prices require the free [Affiliate API](https://portals.aliexpress.com/).
