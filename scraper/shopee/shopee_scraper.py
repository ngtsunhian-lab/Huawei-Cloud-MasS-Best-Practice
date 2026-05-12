"""
Shopee Brazil Product Scraper - Web/SSR approach
Uses Facebook bot User-Agent to get server-rendered product data
from shopee.com.br listing pages with structured data (ld+json).

Data model per page:
- Block 2 (ItemList, no price): search listing URLs for discovery
- Block 3 (Product): featured product with rating
- Block 4 (ItemList, with price): featured context products with prices

Strategy:
- Visit category/search pages with pagination and multiple sort orders
- Collect Block 4 (priced) products from every page
- Collect Block 3 (rating) data and store in a ratings lookup table
- Enrich products with ratings at the end
"""

import requests
import json
import re
import time
from datetime import datetime

HEADERS = {
    'User-Agent': 'facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'pt-BR,pt;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
}

# Category listing pages with multiple sort orders and pages
CATEGORIES = [
    'Celular', 'Smartphone', 'Samsung-Galaxy', 'iPhone', 'Xiaomi', 'Motorola',
    'Tablet', 'Notebook', 'Smartwatch', 'Fone-de-Ouvido', 'Power-Bank',
    'Carregador', 'Capa-de-Celular', 'Película', 'Teclado', 'Mouse',
    'Monitor', 'Impressora', 'Câmera', 'Headphone', 'Webcam', 'SSD',
    'Memória-RAM', 'Processador', 'Placa-de-Vídeo', 'Pendrive', 'HD-Externo',
]

SORT_ORDERS = ['', '?sortBy=pop', '?sortBy=price_asc', '?sortBy=price_desc', '?sortBy=new']

SEARCH_KEYWORDS = [
    'celular samsung', 'iphone apple', 'xiaomi redmi', 'fone bluetooth',
    'smartwatch', 'notebook', 'tablet android', 'power bank',
    'carregador rapido', 'motorola moto', 'realme smartphone',
    'poco xiaomi', 'samsung galaxy a', 'celular 5g', 'celular barato',
    'galaxy s24', 'galaxy s23', 'iphone 14', 'iphone 15', 'xiaomi 14',
    'redmi note', 'oppo reno', 'tecno spark', 'infinix hot',
    'lenovo tab', 'galaxy tab', 'ipad', 'monitor gamer',
    'mouse gamer', 'teclado mecanico', 'headset gamer',
    'ssd nvme', 'pendrive', 'hd externo', 'placa de video',
]


def build_seed_urls():
    """Build URLs in breadth-first order: one sort per category, then next sort, etc."""
    urls = []
    # Round 1: one default page per category (most diverse)
    for cat in CATEGORIES:
        urls.append(f'https://shopee.com.br/list/{cat}')
    # Round 2: search keywords
    for kw in SEARCH_KEYWORDS:
        urls.append(f'https://shopee.com.br/search?keyword={kw.replace(" ", "+")}')
    # Round 3: sort variants (breadth-first — one sort per category before repeating)
    for sort in SORT_ORDERS[1:]:  # skip default (already done)
        for cat in CATEGORIES:
            base = f'https://shopee.com.br/list/{cat}{sort}'
            urls.append(base)
    # Round 4: page 2 for categories (breadth-first)
    for cat in CATEGORIES:
        for sort in SORT_ORDERS:
            base = f'https://shopee.com.br/list/{cat}{sort}'
            sep = '&' if sort else '?'
            urls.append(f'{base}{sep}page=2')
    # Round 5: more search keyword pages
    for kw in SEARCH_KEYWORDS:
        urls.append(f'https://shopee.com.br/search?keyword={kw.replace(" ", "+")}&page=2')
    return urls


session = requests.Session()
session.headers.update(HEADERS)


def parse_price(price_str):
    if not price_str:
        return None
    clean = price_str.replace('R$', '').strip().replace('.', '').replace(',', '.')
    m = re.search(r'[\d.]+', clean)
    if m:
        try:
            v = float(m.group())
            return v if v > 0 else None
        except:
            pass
    return None


def extract_from_html(html, source_url=''):
    """
    Returns:
      products: list of product dicts from ALL ItemList blocks
      featured: dict with item_id, rating, rating_count, brand (or None)
    """
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
                    price_str = item.get('price', '')

                    products.append({
                        'item_id': item_id,
                        'shop_id': shop_id,
                        'name': item.get('name', ''),
                        'price_str': price_str,
                        'price_brl': parse_price(price_str),
                        'image': item.get('image', ''),
                        'url': url,
                        'position': item.get('position', 0),
                        'source': source_url,
                        '_has_price_block': has_price,
                    })

            elif dtype == 'Product':
                url = d.get('url', '')
                m = re.search(r'i\.(\d+)\.(\d+)', url)
                if m:
                    rating_info = d.get('aggregateRating', {}) or {}
                    rval = None
                    rcount = None
                    if isinstance(rating_info, dict):
                        rval = rating_info.get('ratingValue')
                        rcount = (rating_info.get('ratingCount') or
                                  rating_info.get('reviewCount'))
                    brand = d.get('brand', {})
                    brand_name = brand.get('name', '') if isinstance(brand, dict) else ''
                    featured = {
                        'item_id': int(m.group(2)),
                        'shop_id': int(m.group(1)),
                        'rating': rval,
                        'rating_count': rcount,
                        'brand': brand_name,
                        'name': d.get('name', ''),
                        'image': d.get('image', ''),
                        'url': url,
                    }

        except Exception:
            pass

    return products, featured


def fetch_page(url, retries=2):
    for attempt in range(retries + 1):
        try:
            r = session.get(url, timeout=20, allow_redirects=True)
            if r.status_code == 200:
                return r.text
            elif r.status_code == 429:
                time.sleep(15)
            return None
        except Exception:
            if attempt < retries:
                time.sleep(2)
    return None


def run(max_products=600):
    print('=' * 60)
    print('Shopee Brazil Scraper - Web SSR + ld+json approach')
    print('=' * 60)

    seed_urls = build_seed_urls()
    print(f'Total seed URLs: {len(seed_urls)}')

    all_products = {}   # item_id → product dict
    ratings_map = {}    # item_id → {rating, rating_count, brand}
    visited_urls = set()

    for i, url in enumerate(seed_urls):
        if url in visited_urls:
            continue
        visited_urls.add(url)

        html = fetch_page(url)
        if not html:
            continue

        products, featured = extract_from_html(html, url)

        # Store rating from featured (Block 3)
        if featured and featured.get('rating'):
            iid = featured['item_id']
            ratings_map[iid] = {
                'rating': featured['rating'],
                'rating_count': featured['rating_count'],
                'brand': featured.get('brand', ''),
            }
            # Also ensure featured product is in all_products (with rating)
            if iid not in all_products:
                all_products[iid] = {
                    'item_id': featured['item_id'],
                    'shop_id': featured['shop_id'],
                    'name': featured['name'],
                    'price_str': '',
                    'price_brl': None,
                    'image': featured['image'],
                    'url': featured['url'],
                    'rating': featured['rating'],
                    'rating_count': featured['rating_count'],
                    'brand': featured.get('brand', ''),
                    'source': url,
                }
            else:
                all_products[iid]['rating'] = featured['rating']
                all_products[iid]['rating_count'] = featured['rating_count']

        # Store all products from this page
        for p in products:
            iid = p['item_id']
            if iid not in all_products:
                all_products[iid] = p
                all_products[iid]['rating'] = None
                all_products[iid]['rating_count'] = None
                all_products[iid]['brand'] = None
            else:
                # Merge: prefer data with price
                existing = all_products[iid]
                if p.get('price_brl') and not existing.get('price_brl'):
                    existing['price_brl'] = p['price_brl']
                    existing['price_str'] = p['price_str']

        new_priced = sum(1 for p in all_products.values() if p.get('price_brl'))
        if (i + 1) % 10 == 0 or i < 10:
            print(f'  [{i+1}/{len(seed_urls)}] total={len(all_products)} priced={new_priced} | {url[28:75]}')

        if len(all_products) >= max_products:
            break

        time.sleep(0.35)

    # Apply ratings from ratings_map to all products
    for iid, rdata in ratings_map.items():
        if iid in all_products and not all_products[iid].get('rating'):
            all_products[iid]['rating'] = rdata['rating']
            all_products[iid]['rating_count'] = rdata['rating_count']
            all_products[iid]['brand'] = rdata.get('brand', '')

    # Finalize
    products_list = list(all_products.values())
    # Clean up internal flags
    for p in products_list:
        p.pop('_has_price_block', None)

    priced = [p for p in products_list if p.get('price_brl')]
    rated = [p for p in products_list if p.get('rating')]

    print(f'\n{"=" * 60}')
    print(f'Total unique products: {len(products_list)}')
    print(f'With price: {len(priced)}')
    print(f'With rating: {len(rated)}')
    if priced:
        prices = [p['price_brl'] for p in priced]
        print(f'Price range: R${min(prices):.2f} - R${max(prices):.2f}')
        print(f'Avg price: R${sum(prices)/len(prices):.2f}')

    output = {
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'source': 'Shopee Brazil - Web SSR + ld+json structured data',
        'method': 'facebookexternalhit UA → ld+json extraction from shopee.com.br',
        'note': 'Products from server-rendered listing/product pages. Price in BRL.',
        'total_unique_products': len(products_list),
        'with_price': len(priced),
        'with_rating': len(rated),
        'products': products_list,
    }

    out_path = '/Users/jasonhuang/MELI/shoppe/shopee_products.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f'\nSaved to {out_path}')

    print('\nSample priced products:')
    sample = [p for p in priced if p.get('rating')][:3]
    sample += [p for p in priced if not p.get('rating')][:3]
    for p in sample:
        rating_str = f'★{p["rating"]} ({p["rating_count"]}r)' if p.get('rating') else 'no rating'
        print(f'  [{p["item_id"]}] {p["name"][:52]}')
        print(f'    R${p["price_brl"]} | {rating_str}')

    return products_list


if __name__ == '__main__':
    run(max_products=99999)
