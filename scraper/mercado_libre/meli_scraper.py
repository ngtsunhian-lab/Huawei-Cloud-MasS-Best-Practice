"""Scrape MercadoLibre Brazil using the current results-format API."""
import requests, json, time
from datetime import datetime

HEADERS = {
    "authorization": "Bearer APP_USR-7092-031215-44831921c6deeb3c836569a33ca865e5-3215870989",
    "user-agent": "MercadoLibre-Android/10.507.1 (Pixel 7 Pro; Android 13; Build/TQ3A.230901.001)",
    "accept": "application/json",
    "x-platform": "android",
    "accept-language": "pt-BR",
}

def extract_attrs(attributes):
    attrs = {}
    for a in (attributes or []):
        if isinstance(a, dict):
            name = a.get('name', '')
            val = a.get('value_name', '')
            if name and val:
                attrs[name] = val
    return attrs

def extract_product(item):
    price_info = item.get('price', {}) or {}
    inst_info = item.get('installments', {}) or {}
    rev_info = item.get('reviews', {}) or {}
    seller_info = item.get('seller_info', {}) or {}
    disc_label = price_info.get('discount_label', {}) or {}
    tags = item.get('tags', []) or []
    attrs = extract_attrs(item.get('attributes', []))
    lp = item.get('list_picture', {}) or {}
    thumbnail = lp.get('url', '') if isinstance(lp, dict) else ''

    return {
        'id': item.get('id', ''),
        'title': item.get('title', ''),
        'condition': item.get('condition', ''),
        'price_brl': price_info.get('amount'),
        'original_price_brl': price_info.get('original_price'),
        'discount_rate': price_info.get('discount_rate'),
        'discount_label': disc_label.get('text', '') if isinstance(disc_label, dict) else '',
        'installments_count': inst_info.get('quantity'),
        'installments_value_brl': inst_info.get('amount'),
        'installments_rate': inst_info.get('rate', 0),
        'rating': rev_info.get('rating_average'),
        'rating_count': rev_info.get('total'),
        'seller_id': seller_info.get('id'),
        'seller_level': seller_info.get('power_seller_status', ''),
        'official_store': seller_info.get('official_store_name', ''),
        'free_shipping': 'free_shipping' in tags,
        'fulfillment': 'fulfillment' in tags,
        'interest_free': 'interest_free' in tags,
        'category_id': item.get('category_id', ''),
        'url': item.get('permalink', '') or item.get('url', ''),
        'thumbnail': thumbnail,
        'brand': attrs.get('Marca', ''),
        'model': attrs.get('Modelo', '') or attrs.get('Modelo do celular', '') or attrs.get('Modelo detalhado', ''),
        'ram': attrs.get('Memória RAM', ''),
        'storage': attrs.get('Armazenamento', '') or attrs.get('Capacidade de armazenamento', ''),
        'screen': attrs.get('Tamanho da tela', ''),
        'color': attrs.get('Cor', ''),
    }

def scrape_query(query, max_items=100):
    url = "https://frontend.mercadolibre.com/sites/MLB/search"
    seen_ids = set()
    products = []
    offset = 0

    while len(products) < max_items:
        params = {'q': query, 'offset': offset, 'page_size': 50, 'context': 'android'}
        try:
            r = requests.get(url, headers=HEADERS, params=params, timeout=20)
            if r.status_code != 200:
                print(f"  HTTP {r.status_code} at offset {offset}")
                break
            data = r.json()
        except Exception as e:
            print(f"  Error at offset {offset}: {e}")
            break

        # Products are components with type=None containing an 'item' key
        components = data.get('components', [])
        items = [c['item'] for c in components if c.get('type') is None and 'item' in c]

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
        print(f"  offset={offset}: got {len(items)} items ({len(products)} unique, total={total})")
        offset += limit
        if len(products) >= max_items or offset >= min(total, 1000):
            break
        time.sleep(0.5)

    return products[:max_items]

queries = [
    ('celular', 150),
    ('smartphone', 100),
    ('tablet android', 50),
    ('notebook', 50),
    ('fone de ouvido bluetooth', 50),
    ('smartwatch', 50),
    ('power bank', 30),
    ('samsung galaxy', 50),
    ('iphone', 50),
    ('xiaomi redmi', 50),
]

all_products = []
seen_global = set()

for query, limit in queries:
    print(f"\nScraping: '{query}' (max {limit})...")
    products = scrape_query(query, max_items=limit)

    new_count = 0
    for p in products:
        if p['id'] not in seen_global:
            seen_global.add(p['id'])
            all_products.append(p)
            new_count += 1
    print(f"  +{new_count} new unique (running total: {len(all_products)})")
    time.sleep(1)

print(f"\n=== Total unique products: {len(all_products)} ===")

output = {
    'generated_at': datetime.utcnow().isoformat() + 'Z',
    'source': 'MercadoLibre Brazil',
    'queries': [q for q, _ in queries],
    'total_unique_products': len(all_products),
    'products': all_products
}

with open('/tmp/meli_multi_products.json', 'w') as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print("\nTop 5 products:")
for p in all_products[:5]:
    disc = f" ({p['discount_rate']}% OFF)" if p.get('discount_rate') else ""
    print(f"  [{p['query']}] {p['title'][:60]}\n    R${p['price_brl']}{disc} | {p['brand']} | {p['rating']}★ ({p['rating_count']})")

print(f"\nSaved to /tmp/meli_multi_products.json")
