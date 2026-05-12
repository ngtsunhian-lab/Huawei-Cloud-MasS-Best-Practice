"""
AliExpress Brazil Product Scraper

Architecture:
  Phase 1 (no auth): Collect popular product keywords via seo-alphabet endpoint.
    - Fetched directly on ECS server (101.44.196.235) via SSH — avoids ARMCloud
      syncCmd output truncation and works without browser session cookies.
    - Result cached in aliexpress_keywords.json; subsequent runs load from cache.

  Phase 2 (with affiliate credentials): Fetch product details via Affiliate API.
    - api-sg.aliexpress.com/sync — requires app_key + app_secret from
      portals.aliexpress.com (free registration).
    - Run directly from Mac (no proxy needed).

seo-alphabet: 40 pages × 800 keywords = ~32,000 popular keywords with categories.
Affiliate API: up to 50 products per keyword × page; BR prices, PT language.
"""

import os
import json
import time
import hashlib
import subprocess
import requests
import re
from datetime import datetime

# ─── ECS server config (fetches seo-alphabet directly) ───────────────────────
ECS_HOST = '101.44.196.235'
ECS_USER = 'root'
ECS_PASS = 'Mitmproxy@2026'

# ─── AliExpress Affiliate API config ─────────────────────────────────────────
# Register free at: https://portals.aliexpress.com/
# Path: Dashboard → Tools → API → Create App
AFFILIATE_APP_KEY = ''       # e.g. '12345678'
AFFILIATE_APP_SECRET = ''    # e.g. 'abc123def456'
AFFILIATE_API_URL = 'https://api-sg.aliexpress.com/sync'

SEO_ALPHABET_URL = 'https://www.aliexpress.com/fn/seo-alphabet/index'
SEO_PAGE_VERSION = '1d83f91d7b218221cecdf0e9548cad9a'

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KEYWORDS_FILE = os.path.join(BASE_DIR, 'aliexpress_keywords.json')
PRODUCTS_FILE = os.path.join(BASE_DIR, 'aliexpress_products.json')

SEARCH_KEYWORDS = [
    'celular', 'smartphone', 'samsung galaxy', 'iphone', 'xiaomi redmi',
    'fone bluetooth', 'smartwatch', 'notebook', 'tablet android',
    'power bank', 'carregador rapido', 'motorola', 'capa celular',
    'pelicula celular', 'mouse sem fio', 'teclado mecanico',
    'monitor gamer', 'ssd', 'memoria ram', 'pendrive',
]


# ─── ECS SSH helper ──────────────────────────────────────────────────────────

def ecs_run(cmd, timeout=60):
    """Run a shell command on the ECS server via SSH, return stdout string."""
    result = subprocess.run(
        ['sshpass', '-p', ECS_PASS,
         'ssh', '-o', 'StrictHostKeyChecking=no', '-o', 'ConnectTimeout=15',
         f'{ECS_USER}@{ECS_HOST}', cmd],
        capture_output=True, text=True, timeout=timeout
    )
    return result.stdout


# ─── Phase 1: SEO Alphabet keyword harvest via ECS ───────────────────────────

def fetch_seo_page_ecs(page_no):
    """Fetch one seo-alphabet page directly on ECS (no truncation risk)."""
    url = (f'{SEO_ALPHABET_URL}?channel=popular&pageNo={page_no}'
           f'&pageVersion={SEO_PAGE_VERSION}')
    cmd = (
        f"curl -s --max-time 30 "
        f"-H 'Accept: application/json, */*' "
        f"-H 'Accept-Language: pt-BR,pt;q=0.9' "
        f"-H 'Referer: https://www.aliexpress.com/' "
        f"'{url}'"
    )
    raw = ecs_run(cmd, timeout=45)
    try:
        return json.loads(raw)
    except Exception:
        return None


def extract_keywords_from_seo(data):
    """Parse seo-alphabet response into list of {keyword, category, search_url}."""
    items = []
    total_pages = 0
    total_num = 0
    try:
        block = next(iter(data['data']['data'].values()))
        kw_list = block['fields']['list']
        page_info = block['fields'].get('pageInfo', {})
        total_pages = page_info.get('totalPage', 0)
        total_num = page_info.get('totalNum', 0)
        for group in kw_list:
            cat = group.get('category', '')
            for entry in group.get('data', []):
                items.append({
                    'keyword': entry.get('displayName', ''),
                    'category': cat,
                    'search_url': entry.get('url', ''),
                })
    except Exception:
        pass
    return items, total_pages, total_num


def collect_seo_keywords(max_pages=40):
    """Collect popular keywords from seo-alphabet via ECS SSH."""
    print(f'Collecting seo-alphabet keywords via ECS (up to {max_pages} pages)...')
    all_keywords = []
    seen = set()
    server_total = 0

    for page in range(1, max_pages + 1):
        data = fetch_seo_page_ecs(page)
        if not data:
            print(f'  Page {page}: no data, stopping')
            break

        kws, total_pages, total_num = extract_keywords_from_seo(data)
        if total_num:
            server_total = total_num

        new = 0
        for kw in kws:
            key = kw['keyword']
            if key and key not in seen:
                seen.add(key)
                all_keywords.append(kw)
                new += 1

        effective_max = min(max_pages, total_pages) if total_pages else max_pages
        print(f'  Page {page}/{effective_max}: +{new} keywords '
              f'(total {len(all_keywords)}, server total {server_total})')

        if total_pages and page >= total_pages:
            break
        time.sleep(0.3)

    return all_keywords


def load_or_collect_keywords(max_pages=40, force_refresh=False):
    """Load keywords from cache file, or collect fresh via ECS."""
    if not force_refresh and os.path.exists(KEYWORDS_FILE):
        with open(KEYWORDS_FILE, encoding='utf-8') as f:
            cached = json.load(f)
        kws = cached.get('all_keywords', [])
        print(f'Loaded {len(kws)} keywords from cache: {KEYWORDS_FILE}')
        return kws

    all_keywords = collect_seo_keywords(max_pages=max_pages)

    # Build category summary (store up to 50 per cat for quick preview)
    cats = {}
    for kw in all_keywords:
        c = kw['category']
        cats.setdefault(c, []).append(kw['keyword'])
    cat_sample = {c: kws[:50] for c, kws in cats.items()}

    output = {
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'source': 'AliExpress Brazil - seo-alphabet crosslink data',
        'method': 'ECS direct HTTP (no auth required)',
        'total_keywords': len(all_keywords),
        'categories': cat_sample,
        'all_keywords': all_keywords,
    }
    with open(KEYWORDS_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f'Saved {len(all_keywords)} keywords to {KEYWORDS_FILE}')

    return all_keywords


# ─── Phase 2: Affiliate API product search ───────────────────────────────────

def affiliate_sign(params, app_secret):
    """Compute MD5 signature for AliExpress Affiliate API."""
    sign_str = app_secret
    for k in sorted(params.keys()):
        sign_str += k + str(params[k])
    sign_str += app_secret
    return hashlib.md5(sign_str.encode('utf-8')).hexdigest().upper()


def _affiliate_get(params):
    """Send a signed request to the Affiliate API, return parsed JSON or {}."""
    params['sign'] = affiliate_sign(params, AFFILIATE_APP_SECRET)
    try:
        resp = requests.get(AFFILIATE_API_URL, params=params, timeout=20)
        return resp.json()
    except Exception as e:
        print(f'    API error: {e}')
        return {}


def _base_params(method):
    return {
        'method': method,
        'app_key': AFFILIATE_APP_KEY,
        'sign_method': 'md5',
        'timestamp': str(int(time.time() * 1000)),
        'v': '2.0',
        'target_currency': 'BRL',
        'target_language': 'PT',
        'ship_to_country': 'BR',
    }


def _parse_product(p):
    return {
        'title': p.get('product_title', ''),
        'price_brl': float(p.get('sale_price') or 0),
        'original_price_brl': float(p.get('original_price') or 0),
        'discount': p.get('discount', ''),
        'rating': p.get('evaluate_rate', ''),
        'sales': p.get('lastest_volume', 0),
        'category_id': p.get('category_id', ''),
        'image': p.get('product_main_image_url', ''),
        'url': p.get('product_url', ''),
        'shop_id': p.get('shop_id', ''),
        'commission_rate': p.get('commission_rate', ''),
    }


def affiliate_hotproducts(page=1, page_size=50):
    """Fetch hot products via Affiliate API."""
    params = _base_params('aliexpress.affiliate.hotproduct.query')
    params.update({'page_no': str(page), 'page_size': str(page_size),
                   'platform_type': 'APP'})
    data = _affiliate_get(params)
    try:
        result = (data['aliexpress_affiliate_hotproduct_query_response']
                  ['resp_result']['result']['products']['product'])
        return [_parse_product(p) for p in result]
    except Exception:
        return []


def affiliate_search(keyword, page=1, page_size=50):
    """Search products by keyword via Affiliate API."""
    params = _base_params('aliexpress.affiliate.product.query')
    params.update({
        'keywords': keyword,
        'page_no': str(page),
        'page_size': str(page_size),
        'sort': 'SALE_PRICE_ASC',
        'fields': ('commission_rate,sale_price,original_price,discount,product_title,'
                   'product_main_image_url,evaluate_rate,lastest_volume,category_id,'
                   'product_url,shop_id,seller_id'),
    })
    data = _affiliate_get(params)
    try:
        result = (data['aliexpress_affiliate_product_query_response']
                  ['resp_result']['result']['products']['product'])
        return [_parse_product(p) for p in result]
    except Exception:
        return []


# ─── Main ─────────────────────────────────────────────────────────────────────

def run(seo_pages=40, use_affiliate=False, force_refresh_keywords=False):
    print('=' * 60)
    print('AliExpress Brazil Scraper')
    print('=' * 60)

    # ── Phase 1: SEO Alphabet keywords ──────────────────────────────────────
    print('\n[Phase 1] Keyword taxonomy via seo-alphabet...')
    all_keywords = load_or_collect_keywords(
        max_pages=seo_pages, force_refresh=force_refresh_keywords
    )

    cats = {}
    for kw in all_keywords:
        c = kw['category']
        cats.setdefault(c, []).append(kw['keyword'])
    print(f'Categories: {len(cats)}, total keywords: {len(all_keywords)}')
    for cat, kws in sorted(cats.items(), key=lambda x: -len(x[1]))[:10]:
        print(f'  {cat}: {len(kws)}')

    # ── Phase 2: Affiliate API (requires credentials) ───────────────────────
    all_products = []
    if use_affiliate and AFFILIATE_APP_KEY:
        print('\n[Phase 2] Fetching products via Affiliate API...')

        for page in range(1, 4):
            products = affiliate_hotproducts(page=page, page_size=50)
            if products:
                all_products.extend(products)
                print(f'  Hot products page {page}: {len(products)} items')
            time.sleep(0.5)

        seen_titles = {p['title'] for p in all_products}
        for kw in SEARCH_KEYWORDS:
            products = affiliate_search(kw, page=1, page_size=50)
            if products:
                new = [p for p in products if p['title'] not in seen_titles]
                seen_titles.update(p['title'] for p in new)
                all_products.extend(new)
                print(f'  Keyword "{kw}": {len(new)} new products '
                      f'(total {len(all_products)})')
            time.sleep(0.5)
    else:
        if not AFFILIATE_APP_KEY:
            print('\n[Phase 2] Skipped — set AFFILIATE_APP_KEY + AFFILIATE_APP_SECRET')
            print('  Register free at: portals.aliexpress.com')
            print('  Dashboard → Tools → API → Create App')

    # ── Output ───────────────────────────────────────────────────────────────
    priced = [p for p in all_products if p.get('price_brl')]

    cat_summary = {}
    for cat, kws in cats.items():
        cat_summary[cat] = {'count': len(kws), 'sample': kws[:20]}

    output = {
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'source': 'AliExpress Brazil',
        'method': ('Phase1: seo-alphabet keyword harvest via ECS direct HTTP; '
                   'Phase2: Affiliate API (requires credentials)'),
        'note': (
            'Phase 1: popular product keywords with categories (no prices). '
            'Full keyword list in aliexpress_keywords.json. '
            'Phase 2: products with prices/ratings via Affiliate API.'
        ),
        'keyword_taxonomy': {
            'total_keywords': len(all_keywords),
            'categories': cat_summary,
        },
        'total_products': len(all_products),
        'with_price': len(priced),
        'products': all_products,
    }

    with open(PRODUCTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f'\nSaved to {PRODUCTS_FILE}')

    if priced:
        prices = [p['price_brl'] for p in priced]
        print(f'Price range: R${min(prices):.2f} – R${max(prices):.2f}')
        print(f'Avg price: R${sum(prices) / len(prices):.2f}')
        print('\nSample products:')
        for p in priced[:5]:
            print(f'  {p["title"][:60]}')
            print(f'    R${p["price_brl"]} | {p.get("discount", "")} | '
                  f'{p.get("rating", "")}% rated | {p.get("sales", "")} sold')

    return output


if __name__ == '__main__':
    run(seo_pages=40, use_affiliate=bool(AFFILIATE_APP_KEY))
