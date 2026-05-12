# Shopee Brazil 商品数据爬取 — 技术架构文档

> 生成时间：2026-05-09 · 数据量：2059 件商品（224 件有价格，101 件有评分）· 平台：Shopee Brazil

---

## 目录

1. [项目概览与挑战](#1-项目概览与挑战)
2. [整体技术架构](#2-整体技术架构)
3. [技术调研：API 探索全过程](#3-技术调研api-探索全过程)
4. [最终解决方案：Facebook Bot SSR + ld+json](#4-最终解决方案facebook-bot-ssr--ldjson)
5. [数据结构解析](#5-数据结构解析)
6. [爬取流程详解](#6-爬取流程详解)
7. [数据成果统计](#7-数据成果统计)
8. [与 MercadoLibre 方案对比](#8-与-mercadolibre-方案对比)
9. [Shopee 反爬机制深度分析](#9-shopee-反爬机制深度分析)

---

## 1. 项目概览与挑战

### 目标

抓取 Shopee Brazil 主购物站（`shopee.com.br`）商品数据，获取商品名称、价格、评分、品牌等结构化信息。
**注意：要求使用 shopee.com.br 主站数据，不使用 sv.shopee.com.br 社交流数据。**

### 核心挑战

Shopee Brazil 实施了业界最严格的反爬保护体系：

```
挑战层级：

Layer 1: API 鉴权                   ← 需要 JWT Token / Cookie
Layer 2: Anti-Bot 加密 Token        ← 每请求重新生成，无法复制
Layer 3: 设备指纹绑定               ← Token 与设备ID绑定
Layer 4: 服务端行为检测             ← 即使Token合法也可能返回418
Layer 5: 代理/MitM 检测            ← 检测到流量拦截则屏蔽内容API
```

**最终结果：所有常规商品 API 全部被封锁（error 90309999 / 418 / 403），
通过发现 Facebook Bot User-Agent 触发 SSR 并提取 ld+json 结构化数据绕过限制。**

---

## 2. 整体技术架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                           研究基础设施                                │
│                                                                     │
│  ┌──────────────────┐   ┌──────────────────┐   ┌────────────────┐  │
│  │  ARMCloud 云手机  │   │   ECS 服务器      │   │   本地 Mac     │  │
│  │  PAD: ACP61H5FU6 │──▶│  mitmproxy 8080   │   │  Python 脚本  │  │
│  │  Android 13      │   │  101.44.196.235   │   │  scraper.py   │  │
│  │  Yuzu Browser    │   │  流量日志分析      │   │               │  │
│  └──────────────────┘   └──────────────────┘   └────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                                          │
                                      Facebook Bot UA (facebookexternalhit/1.1)
                                                          │
                                                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    shopee.com.br (主购物站 - SSR 模式)                 │
│                                                                     │
│    GET /list/{Category}                                             │
│    GET /search?keyword=...                                          │
│    ├── 触发服务端渲染 (SSR) → 返回完整 HTML                           │
│    └── HTML 中包含 5 个 ld+json 结构化数据块                          │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼ HTML (含 ld+json 结构化数据)
┌─────────────────────────────────────────────────────────────────────┐
│                         ld+json 数据提取层                             │
│                                                                     │
│  Block 1: WebSite                   ← 站点信息（忽略）                │
│  Block 2: BreadcrumbList            ← 面包屑（忽略）                  │
│  Block 3: ItemList (无价格)          ← 搜索结果URL列表（发现用）        │
│  Block 4: Product (有评分，无价格)   ← 精选商品详情 → ratings_map       │
│  Block 5: ItemList (有价格)          ← 精选上下文商品 → all_products    │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                    /Users/jasonhuang/MELI/shoppe/shopee_products.json
```

---

## 3. 技术调研：API 探索全过程

### 3.1 基础设施搭建

通过 ARMCloud API 控制云手机，Clash 代理 + mitmproxy 拦截 HTTPS 流量：

```
ARMCloud 手机 → Clash 透明代理 (iptables CLASH chain)
              → SOCKS5 (mitmproxy:8080 on ECS 101.44.196.235)
              → Shopee 服务器
                    ↓ 同时记录
         mitmproxy CA 证书安装为系统信任证书
         日志：/var/log/mitmproxy/flows-2026-05-09.jsonl（2000+ 条）
```

Clash 配置关键点：
- 监听：52220（redir）、57891（SOCKS5）
- iptables CLASH chain 重定向所有 TCP/UDP
- DIRECT 豁免 UID：1000、10018、10063（系统进程）
- 其他所有流量 → ECS 101.44.196.235:8080 SOCKS5

### 3.2 流量分析：各 API 状态

通过对 mitmproxy 流量日志进行分析，所有 Shopee API 按状态分类：

```
❌ 418 Anti-Bot 拦截（内容类API全部封锁，error 90309999）：
┌──────────────────────────────────────────────────────────┐
│ POST /api/v4/native/homepage                              │
│ GET  /api/v4/search/search_page_common?keyword=celular    │
│ GET  /api/v4/recommend/recommend?bundle=category_landing  │
│      &catid=11 (Celulares e Smartphones)                  │
│ GET  /api/v4/pdp/get (商品详情页)                          │
│ POST /api/v4/cart/get                                     │
└──────────────────────────────────────────────────────────┘

❌ 403 直接拒绝：
┌──────────────────────────────────────────────────────────┐
│ GET /api/v4/search/search_items?keyword=celular           │
│ GET /api/v4/flash_sale/get_all_sessions                   │
│ GET /api/v4/item/get?itemid=...&shopid=...               │
└──────────────────────────────────────────────────────────┘

✅ 200 正常响应（工具类API及 Facebook Bot SSR）：
┌──────────────────────────────────────────────────────────┐
│ GET shopee.com.br/list/Celular  (facebookexternalhit UA)  │  ← 突破口
│ GET shopee.com.br/search?keyword=celular (facebookexternalhit UA)
│ GET /api/v4/itemcard/set/elements                         │
│ GET /api/v4/account/basic/get_account_info               │
│ POST /api/v1/configs                                      │
└──────────────────────────────────────────────────────────┘
```

### 3.3 关键发现：API 封锁是端点级别的

实验证明封锁是 API 端点级别的（并非仅本设备）：

```python
# 测试结论：无论 Cookie 如何，内容API均返回418
tests = [
    ('无Cookie',         {}),                           # → 418
    ('仅SPC_F',          {'Cookie': 'SPC_F=...'}),      # → 418
    ('全新随机设备ID',     {'Cookie': 'SPC_DID=xxx'}),   # → 418
    ('完整手机Cookie',    {'Cookie': '...SPC_U=...'}),   # → 418
]
# 结论：Shopee 对 shopee.com.br 内容API实施了全面封锁
# 但 Facebook Bot UA 触发 SSR 返回 ld+json 结构化数据，绕过了内容API封锁
```

### 3.4 浏览器方案的局限性

Yuzu 浏览器（UID 10062）加载 shopee.com.br/list/Celular：
- 返回 246KB HTML，但为 React CSR shell（无商品内容）
- 等待 45 秒后 JS 仍未发出有效商品 API 请求
- 原因：Shopee 的 JS 调用的商品 API 全部被 418 封锁

**结论**：浏览器方案在 Shopee 反爬策略下无效，必须用 Facebook Bot SSR 方案。

---

## 4. 最终解决方案：Facebook Bot SSR + ld+json

### 4.1 发现过程

Facebook 等社交平台抓取链接预览时，Shopee 需要返回完整内容（Open Graph / SEO 要求）。
使用 `facebookexternalhit/1.1` User-Agent 访问列表页时：

```
Chrome UA → CSR shell (无商品数据)    ❌
Facebook Bot UA → SSR HTML (含 ld+json 结构化数据)  ✅
Googlebot → 403  ❌
Twitterbot → 403  ❌
```

Shopee 只对 Facebook Bot 开放 SSR，可能因为 Facebook 是最重要的外链来源之一。

### 4.2 请求方式

```http
GET /list/Celular HTTP/1.1
Host: shopee.com.br
User-Agent: facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)
Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8
Accept-Language: pt-BR,pt;q=0.9
Accept-Encoding: gzip, deflate, br
Connection: keep-alive
```

**无需 Cookie、无需加密 Token**，直接访问即可。

### 4.3 URL 来源

```python
# 类目页
https://shopee.com.br/list/{Category}
# 类目页 + 排序
https://shopee.com.br/list/{Category}?sortBy=pop
https://shopee.com.br/list/{Category}?sortBy=price_asc
https://shopee.com.br/list/{Category}?sortBy=price_desc
https://shopee.com.br/list/{Category}?sortBy=new
# 类目页 + 分页
https://shopee.com.br/list/{Category}?page=2
# 搜索页
https://shopee.com.br/search?keyword=celular+samsung
```

---

## 5. 数据结构解析

### 5.1 ld+json 块结构

每个 shopee.com.br 列表页包含 5 个 `<script type="application/ld+json">` 块：

```
Block 1: {"@type": "WebSite"}              ← 站点基础信息（忽略）
Block 2: {"@type": "BreadcrumbList"}       ← 面包屑导航（忽略）
Block 3: {"@type": "ItemList"}  (无价格)    ← 搜索结果产品 URL 列表
Block 4: {"@type": "Product"}   (有评分)    ← 精选产品详情（含 aggregateRating）
Block 5: {"@type": "ItemList"}  (有价格)    ← 精选上下文产品（含 price）
```

**采集策略**：
- Block 3（ItemList，无价格）→ 产品 ID 发现
- Block 4（Product）→ 存入 `ratings_map`（item_id → rating 信息）
- Block 5（ItemList，有价格）→ 存入 `all_products`

### 5.2 产品 URL 编码

```
https://shopee.com.br/xxx-i.{shop_id}.{item_id}
                              ↑         ↑
                        正则提取: r'i\.(\d+)\.(\d+)'
```

### 5.3 Block 4 Product 结构（评分来源）

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

### 5.4 Block 5 ItemList 结构（价格来源）

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

### 5.5 价格解析

```python
def parse_price(price_str):
    # "R$899,00" → 899.0
    clean = price_str.replace('R$', '').strip().replace('.', '').replace(',', '.')
    m = re.search(r'[\d.]+', clean)
    return float(m.group()) if m else None
```

### 5.6 输出字段

| 字段 | 类型 | 来源 | 说明 |
|------|------|------|------|
| `item_id` | int | URL 正则 | Shopee 商品 ID |
| `shop_id` | int | URL 正则 | 店铺 ID |
| `name` | str | Block 4/5 | 完整商品名称 |
| `price_str` | str | Block 5 | 原始价格字符串，如 "R$899,00" |
| `price_brl` | float | Block 5 | 价格（BRL） |
| `image` | str | Block 4/5 | 商品图片 URL |
| `url` | str | Block 4/5 | 商品页面 URL |
| `position` | int | Block 5 | 列表中的位置 |
| `rating` | float | Block 4 | 评分（0-5） |
| `rating_count` | str/int | Block 4 | 评分数量 |
| `brand` | str | Block 4 | 品牌名称 |
| `source` | str | 内部 | 来源 URL |

---

## 6. 爬取流程详解

### 6.1 Seed URL 构建策略（广度优先）

```python
def build_seed_urls():
    # Round 1: 每个类目各一页（最多样化）
    for cat in CATEGORIES:        # 27 个类目
        urls.append(f'/list/{cat}')

    # Round 2: 搜索关键词
    for kw in SEARCH_KEYWORDS:    # 36 个关键词
        urls.append(f'/search?keyword={kw}')

    # Round 3: 排序变体（广度优先，同一类目的不同排序交替）
    for sort in ['?sortBy=pop', '?sortBy=price_asc', '?sortBy=price_desc', '?sortBy=new']:
        for cat in CATEGORIES:
            urls.append(f'/list/{cat}{sort}')

    # Round 4: 第 2 页（各类目 × 各排序）
    for cat in CATEGORIES:
        for sort in SORT_ORDERS:
            urls.append(f'/list/{cat}{sort}&page=2')

    # Round 5: 搜索关键词第 2 页
    for kw in SEARCH_KEYWORDS:
        urls.append(f'/search?keyword={kw}&page=2')
```

**广度优先的原因**：每个类目页的 Block 4 精选商品（带评分）只有 1 件，
若先遍历完一个类目的所有排序和分页，会反复看到同一件精选商品；
广度优先则优先覆盖更多类目，最大化 ratings_map 中商品多样性。

### 6.2 主采集流程

```
初始化 all_products = {}   # item_id → product
        ratings_map = {}   # item_id → {rating, rating_count, brand}
        visited_urls = set()
   │
   ▼
遍历 seed_urls（最多 max_products 件）
   │
   ├── fetch_page(url)  → HTML
   │
   ├── extract_from_html(html) → (products_list, featured_dict)
   │        │
   │        ├── 扫描所有 ld+json 块
   │        ├── ItemList 块 → products_list（有/无价格均收集）
   │        └── Product 块 → featured_dict（含评分）
   │
   ├── 若 featured 有评分 → 存入 ratings_map[item_id]
   │
   ├── 遍历 products_list
   │        ├── 未见过 → all_products[item_id] = product
   │        └── 已见过 → 若新数据有价格而旧数据无价格，则合并价格
   │
   └── sleep(0.35)

   ▼
评分回填：对 ratings_map 中每个 item_id
          若在 all_products 中存在且无评分 → 写入评分数据

   ▼
输出 shopee_products.json
```

### 6.3 限速与重试

```python
def fetch_page(url, retries=2):
    for attempt in range(retries + 1):
        try:
            r = session.get(url, timeout=20, allow_redirects=True)
            if r.status_code == 200:
                return r.text
            elif r.status_code == 429:
                time.sleep(15)   # 限速时等待 15 秒
            return None
        except Exception:
            if attempt < retries:
                time.sleep(2)    # 网络错误重试等待 2 秒
    return None

# 正常请求间隔
time.sleep(0.35)  # 每页 350ms
```

---

## 7. 数据成果统计

### 7.1 采集规模

| 指标 | 数值 |
|------|------|
| 唯一商品总数 | **2,059 件** |
| 有价格商品 | **224 件** (10.9%) |
| 有评分商品 | **101 件** (4.9%) |
| 类目数量 | 27 个 |
| 搜索关键词 | 36 个 |
| Seed URL 总数 | ~540 个 |
| 商品价格范围 | R$1.97 — R$4,079.00 |
| 均价 | R$218.72 |

### 7.2 数据完整性分析

| 字段 | 有效率 | 备注 |
|------|--------|------|
| name | ~100% | 所有 Block 3/5 均有名称 |
| url | ~100% | URL 包含 shop_id + item_id |
| image | ~95% | 少量商品无图 |
| price_brl | 10.9% (224/2059) | 仅 Block 5 有价格 |
| rating | 4.9% (101/2059) | 仅 Block 4 有评分 |
| brand | 4.9% (101/2059) | 与评分同源（Block 4） |

**价格覆盖率低的根本原因**：
- Block 3（发现用 ItemList）贡献大量 item_id 但无价格
- Block 5（有价格）每页只有约 10-20 件商品
- Block 4（有评分）每页只有 1 件精选商品
- 商品详情页以 Facebook Bot UA 访问时只返回 WebSite + BreadcrumbList，无商品数据

### 7.3 价格分布

```
0-50      ████████               ~15件
50-100    ████████████████       ~45件
100-200   ████████████████████   ~60件
200-500   ████████████           ~65件
500-1000  ████████               ~25件
1000+     ████████               ~14件
```

---

## 8. 与 MercadoLibre 方案对比

```
                    MercadoLibre                   Shopee (本方案)
                    ────────────────               ──────────────────────────
数据来源             商品搜索 API（直接）             Facebook Bot SSR ld+json
端点                 frontend.mercadolibre.com      shopee.com.br（HTML）
鉴权方式             APK内嵌 Bearer Token            无需 Cookie/Token
Anti-Bot Token       不需要                          不需要（Bot SSR豁免）
数据格式             直接 JSON                       HTML 解析 → ld+json
价格覆盖率           100%（524/524）                10.9%（224/2059）
评分覆盖率           约80%                          4.9%（101/2059）
商品总量             524 件（10 个关键词）            2059 件（27类目 + 36关键词）
有价格商品量          524 件                          224 件
丰富度               评分、卖家等级、品牌、型号        评分、品牌（仅精选商品）
分类精准度           高（按关键词搜索）               中（类目宽泛）
采集效率             高（20-28件/请求）               低（10-20件有价/页）
```

**核心差异**：MercadoLibre 对移动端搜索 API 开放（Bearer Token 即可），
Shopee 对所有商品内容 API 实施全面封锁，只有 Facebook Bot SSR 路径可用。

---

## 9. Shopee 反爬机制深度分析

### 9.1 加密 Token 体系

从 mitmproxy 捕获的请求头中发现多层加密：

```http
# 请求级别加密 Token（每次请求重新生成）
af-ac-enc-sz-token: qsDsbaI02HwkVSej8bB/aQ==|QtIsGcr+Pi03...  ← 主要反Bot Token
sfid:               8fW0FooEgL+SHMgy1ZnGVg==|RdIsGcr+Pi03...  ← Session指纹
x-sap-ri:           e53fff6982d7bc0d371a711a01f3927e73e9dc...  ← 请求完整性签名
fb97709:            YrT4A0l/2HLy5j8YuVzYD8Rdxb8=              ← 设备绑定签名
832dfed5:           tU/ei0De9pRgXlZT2G7oPyQo7/B=              ← 时间戳绑定

# 这些 Token 由 Shopee 安全 SDK 实时生成，无法通过逆向单次复现
```

### 9.2 封锁维度

```
维度1：IP 维度
  · 数据中心IP → 大概率直接封锁

维度2：Token 维度
  · 无加密Token → 403（直接拒绝）
  · 有Token但伪造 → 418（识别异常，error 90309999）
  · 有Token且合法（来自真实手机）→ 418（端点级全面封锁）

维度3：行为维度
  · 访问频率过高 → 限速或封锁

维度4：User-Agent 维度（最关键发现）
  · 普通 Chrome UA → CSR Shell，无商品数据
  · Googlebot → 403 直接拒绝
  · Twitterbot → 403 直接拒绝
  · facebookexternalhit/1.1 → SSR HTML，含 ld+json 结构化数据 ✅
```

### 9.3 为什么 Facebook Bot UA 有效？

```
推测原因：
  1. Shopee 需要 Facebook 链接预览正常工作（Facebook 是主要流量来源）
  2. Open Graph / Schema.org 数据对 SEO 和社交分享至关重要
  3. Facebook 爬取是单页面、低频、正当的，Shopee 无法拒绝

限制：
  · 每页 Block 4 只有 1 件带评分的精选商品
  · 每页 Block 5 只有约 10-20 件带价格的上下文商品
  · 商品详情页（/product/{shop_id}/{item_id}）以 Facebook Bot 访问无商品数据
  · 无法直接枚举所有商品，只能通过类目/搜索页间接发现
```

---

## 附录：核心代码

### extract_from_html 函数

```python
def extract_from_html(html, source_url=''):
    """返回 (products列表, featured商品dict 或 None)"""
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

### 评分回填

```python
# Phase 1 采集时存储评分
if featured and featured.get('rating'):
    ratings_map[featured['item_id']] = {
        'rating': featured['rating'],
        'rating_count': featured['rating_count'],
        'brand': featured.get('brand', ''),
    }

# Phase 1 结束后回填
for iid, rdata in ratings_map.items():
    if iid in all_products and not all_products[iid].get('rating'):
        all_products[iid]['rating'] = rdata['rating']
        all_products[iid]['rating_count'] = rdata['rating_count']
        all_products[iid]['brand'] = rdata.get('brand', '')
```

---

*文档生成于 2026-05-09 | 数据文件：`/Users/jasonhuang/MELI/shoppe/shopee_products.json`*
*方案：shopee.com.br SSR via facebookexternalhit/1.1 UA + ld+json structured data extraction*
