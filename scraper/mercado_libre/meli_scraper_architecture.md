# MercadoLibre Brazil 商品数据爬取 — 技术架构文档

> 生成时间：2026-05-12 · 数据量：524 件唯一商品 · 平台：MercadoLibre Brazil (MLB)

---

## 目录

1. [项目概览](#1-项目概览)
2. [整体技术架构](#2-整体技术架构)
3. [API 逆向分析](#3-api-逆向分析)
4. [爬取流程详解](#4-爬取流程详解)
5. [数据结构解析](#5-数据结构解析)
6. [反爬处理与鉴权机制](#6-反爬处理与鉴权机制)
7. [去重与分页策略](#7-去重与分页策略)
8. [数据成果统计](#8-数据成果统计)
9. [关键问题与解决方案](#9-关键问题与解决方案)

---

## 1. 项目概览

### 目标

抓取 MercadoLibre Brazil（美客多巴西站）电子产品类目商品数据，覆盖手机、平板、笔记本、耳机、智能手表等品类，获取商品标题、价格、折扣、安装分期、评分、卖家信息、品牌型号等结构化数据。

### 技术路线选择

```
方案A：浏览器爬取 HTML          ❌ 渲染复杂、结构不稳定
方案B：官方 Partner API         ❌ 需要商户资质审批
方案C：逆向 Android App 内部 API ✅ 数据结构化、无需登录、返回完整字段
```

**最终选择**：逆向 MercadoLibre Android App 调用的内部搜索 API，通过模拟 App 请求头直接调用，无需安装 App 或浏览器。

---

## 2. 整体技术架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        本地 Mac 机器                             │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │               meli_v3_scraper.py                        │   │
│  │                                                         │   │
│  │  ┌──────────┐    ┌──────────┐    ┌──────────────────┐  │   │
│  │  │ 查询列表  │───▶│ 分页控制  │───▶│  HTTP 请求构造   │  │   │
│  │  │ 10 个关键│    │ offset++ │    │  伪装 Android    │  │   │
│  │  │ 词 + 配额│    │ limit=20 │    │  Headers + Token │  │   │
│  │  └──────────┘    └──────────┘    └────────┬─────────┘  │   │
│  │                                           │            │   │
│  │  ┌──────────────────────────────────────┐ │            │   │
│  │  │         全局去重集合 seen_global      │◀┤            │   │
│  │  │         (基于 item.id)               │ │            │   │
│  │  └──────────────────────────────────────┘ │            │   │
│  └────────────────────────────────────────────┼────────────┘   │
│                                               │                │
└───────────────────────────────────────────────┼────────────────┘
                                                │ HTTPS
                                                ▼
┌─────────────────────────────────────────────────────────────────┐
│              MercadoLibre CDN / API 网关                         │
│                                                                 │
│    frontend.mercadolibre.com/sites/MLB/search                   │
│                                                                 │
│    ┌─────────────┐    ┌──────────────┐    ┌─────────────────┐  │
│    │ 请求鉴权     │    │ 搜索排序引擎  │    │  商品数据库      │  │
│    │ Bearer Token│    │ 28,000+ SKU  │    │  attributes     │  │
│    │ User-Agent  │    │  分页返回     │    │  pricing engine │  │
│    └─────────────┘    └──────────────┘    └─────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                                                │
                                                ▼ JSON Response
┌─────────────────────────────────────────────────────────────────┐
│                    数据处理层                                     │
│                                                                 │
│   extract_product()  ──▶  字段标准化  ──▶  类型转换             │
│   extract_attrs()    ──▶  属性展平    ──▶  品牌/型号/颜色提取   │
│                                                                 │
│                    ▼                                            │
│            /tmp/meli_multi_products.json                        │
│                    ▼                                            │
│        SCP 上传至 ECS 101.44.196.235                            │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. API 逆向分析

### 3.1 端点发现

通过对 MercadoLibre Android App 流量进行 mitmproxy 抓包，发现搜索功能调用的核心端点：

```
GET https://frontend.mercadolibre.com/sites/MLB/search
```

### 3.2 请求参数

| 参数 | 值 | 说明 |
|------|-----|------|
| `q` | `celular` | 搜索关键词（葡萄牙语） |
| `offset` | `0, 20, 40, ...` | 分页偏移量 |
| `page_size` | `50` | 期望每页数量（实际返回约 20-28） |
| `context` | `android` | 触发 Android 专属响应格式 |

### 3.3 鉴权 Headers

```http
GET /sites/MLB/search?q=celular&offset=0&page_size=50&context=android HTTP/1.1
Host: frontend.mercadolibre.com
authorization: Bearer APP_USR-7092-031215-44831921c6deeb3c836569a33ca865e5-3215870989
user-agent: MercadoLibre-Android/10.507.1 (Pixel 7 Pro; Android 13; Build/TQ3A.230901.001)
accept: application/json
x-platform: android
accept-language: pt-BR
```

**关键字段说明：**

- `authorization`：App 级 Bearer Token（非用户级），嵌入在 APK 中，无需登录即可使用
- `user-agent`：精确模拟 Android 10.507.1 版本的 Pixel 7 Pro 设备
- `x-platform: android`：告知服务端返回 Android 专用 JSON 格式（而非 Web HTML）
- `accept-language: pt-BR`：返回巴西葡萄牙语内容和货币（BRL）

### 3.4 API 响应格式演变（关键坑点）

本项目经历了 API 格式的两次变化：

```
版本 1（早期）：components 数组，含 POLYCARD / SEARCH_RESULT_ITEM 类型
     │
     ▼
版本 2（中期）：results 数组，平铺商品对象
     │
     ▼
版本 3（当前）：components 数组，type=None 的对象包含 item 字段
```

**当前格式（版本 3）响应结构：**

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
      "item": { ... }          ← 商品数据在这里
    },
    {
      "id": "...",
      "type": "FILTER_SPECIALIZED",   ← 过滤器组件，跳过
      ...
    },
    {
      "id": "...",
      "type": "CAROUSEL",             ← 轮播组件，跳过
      ...
    }
  ]
}
```

**核心规律**：产品组件的 `type` 字段为 `null`（Python 中为 `None`），其余为 UI 组件（过滤器、轮播等）。

---

## 4. 爬取流程详解

### 4.1 主流程

```
开始
  │
  ▼
初始化全局去重集合 seen_global = set()
  │
  ▼
遍历查询列表（10个关键词）
  │
  ├─▶ query="celular",       limit=150
  ├─▶ query="smartphone",    limit=100
  ├─▶ query="tablet android",limit=50
  ├─▶ query="notebook",      limit=50
  ├─▶ query="fone bluetooth",limit=50
  ├─▶ query="smartwatch",    limit=50
  ├─▶ query="power bank",    limit=30
  ├─▶ query="samsung galaxy",limit=50
  ├─▶ query="iphone",        limit=50
  └─▶ query="xiaomi redmi",  limit=50
  │
  ▼
对每个 query 执行 scrape_query()
  │
  ▼
全局去重 → 追加到 all_products
  │
  ▼
输出 JSON 文件
  │
  ▼
SCP 传输至 ECS
  │
  结束
```

### 4.2 单查询爬取循环（scrape_query）

```
scrape_query(query="celular", max_items=150)
  │
  ├── offset = 0
  │     │
  │     ▼
  │   GET /search?q=celular&offset=0&page_size=50
  │     │
  │     ▼
  │   解析 components → 提取 type=None 的 item
  │     │
  │     ├── 得到 28 个 items
  │     ├── 去重后加入 products（本查询去重）
  │     └── offset += paging.limit (= 20)
  │
  ├── offset = 20 → 再请求 → 得到 28 items
  ├── offset = 40 → 再请求 → 得到 28 items
  ├── offset = 60 → 再请求 → 得到 27 items
  ├── offset = 80 → 已满 150 条 → 截断
  │
  └── 返回 products[:max_items]
```

### 4.3 分页逻辑

```python
# 每轮结束后的翻页控制
offset += limit          # limit 从 paging.limit 动态读取（当前=20）
if len(products) >= max_items:
    break                # 达到本查询配额，停止
if offset >= min(total, 1000):
    break                # 不超过 API 允许最大 offset=1000
time.sleep(0.5)          # 礼貌性延迟，避免触发速率限制
```

**为何 API 限制 offset ≤ 1000？**
MercadoLibre 的搜索结果仅对前 1000 条结果开放翻页（`primary_results: 1000`），超过后返回空结果，这是其反爬策略的一部分。

---

## 5. 数据结构解析

### 5.1 商品字段提取逻辑

```
API 返回的 item 对象
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
│     └── .rate                      → product.installments_rate  (0=免息)
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
└── item.attributes[]                → extract_attrs() → 属性字典
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

### 5.2 属性展平函数

```python
def extract_attrs(attributes):
    attrs = {}
    for a in (attributes or []):
        if isinstance(a, dict):
            name = a.get('name', '')      # 属性名（葡萄牙语）
            val = a.get('value_name', '') # 属性值
            if name and val:
                attrs[name] = val
    return attrs
```

API 返回的属性数组最多含 14 个字段，上述函数将其转为平铺字典，再按语言键名提取目标字段。

### 5.3 输出 JSON 结构

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

---

## 6. 反爬处理与鉴权机制

### 6.1 鉴权体系分析

```
MercadoLibre 鉴权层级：

Level 1: App-level Bearer Token
┌────────────────────────────────────────────────────────┐
│  APP_USR-7092-031215-44831921c6deeb3c836569a33ca865e5  │
│  · 硬编码在 APK 中                                      │
│  · 标识应用身份，非用户身份                              │
│  · 无需登录即可调用搜索接口                              │
│  · 长期有效（需定期更新 APK 获取新 Token）               │
└────────────────────────────────────────────────────────┘

Level 2: User-Agent 校验
┌────────────────────────────────────────────────────────┐
│  MercadoLibre-Android/10.507.1 (Pixel 7 Pro; ...)      │
│  · 服务端根据 UA 决定返回格式（Android JSON vs Web HTML）│
│  · 缺少此 UA 将返回 Web 格式或被拒绝                    │
└────────────────────────────────────────────────────────┘

Level 3: Platform Header
┌────────────────────────────────────────────────────────┐
│  x-platform: android                                   │
│  · 双重确认平台类型                                     │
│  · 触发 Android 专用 API 响应路径                       │
└────────────────────────────────────────────────────────┘
```

### 6.2 速率限制规避

| 策略 | 实现方式 |
|------|----------|
| 请求间隔 | 每页请求后 `sleep(0.5)` |
| 查询间隔 | 每个关键词完成后 `sleep(1)` |
| 超时控制 | `timeout=20` 秒，避免长时阻塞 |
| 错误处理 | HTTP 非 200 时停止当前查询，不中断全局 |

### 6.3 与 Shopee 的对比

```
MercadoLibre                    Shopee
─────────────────────────────   ──────────────────────────────
Bearer Token（APK内嵌）✅       SPC_U Cookie（用户登录态）❌
无设备指纹检测 ✅               设备ID黑名单机制 ❌
搜索接口完全开放 ✅             搜索接口返回 418 (error 90309999) ❌
无 TLS 指纹检测 ✅              服务端行为检测 ❌
```

---

## 7. 去重与分页策略

### 7.1 两级去重机制

```
Level 1：单查询去重（seen_ids）
┌─────────────────────────────────────────┐
│ scrape_query() 内部                      │
│                                         │
│  seen_ids = set()                       │
│  for item in page_results:              │
│    if item.id not in seen_ids:          │
│      seen_ids.add(item.id)              │
│      products.append(item)             │
│                                         │
│ 目的：防止同一查询翻页时出现重复商品      │
└─────────────────────────────────────────┘

Level 2：全局去重（seen_global）
┌─────────────────────────────────────────┐
│ 主流程                                   │
│                                         │
│  seen_global = set()                    │
│  for query, limit in queries:           │
│    products = scrape_query(query)       │
│    for p in products:                   │
│      if p.id not in seen_global:        │
│        seen_global.add(p.id)            │
│        all_products.append(p)           │
│                                         │
│ 目的：Samsung Galaxy 可能同时出现在      │
│ "celular"、"smartphone"、"samsung"查询  │
│ 中，全局去重确保每个商品只保留一次       │
└─────────────────────────────────────────┘
```

### 7.2 为何跨查询会有大量重复？

```
查询 "celular"      ──────────────────────┐
查询 "smartphone"   ─────────────────┐   │  Samsung Galaxy A17
查询 "samsung galaxy" ──────────┐   │   │  出现在以上多个查询
                                 ▼   ▼   ▼
                              全局去重集合
                              仅保留第一次出现
```

这是爬取多关键词时的常见现象。本项目 10 个查询理论上可收集 630 条，实际得到 524 条唯一商品（重复率约 17%）。

### 7.3 分页边界控制

```
可用范围：offset 0 → 1000（API 硬限制）
实际分页：每步 20（由 paging.limit 决定）
最多翻页：50 次 × 20 = 1000 条/查询

查询 "celular" 实际 total = 28,557 条
但 API 仅开放前 1000 条 → 我们按配额 150 条限停
```

---

## 8. 数据成果统计

### 8.1 采集规模

| 指标 | 数值 |
|------|------|
| 唯一商品总数 | **524 件** |
| 涵盖查询关键词 | 10 个 |
| 价格范围 | R$18 — R$14,984 |
| 均价 | R$1,950 |
| 采集耗时 | ~3 分钟 |

### 8.2 各查询数据量

```
celular              ████████████████████████████████  150 件
tablet android       ████████████                       50 件
notebook             ████████████                       50 件
fone bluetooth       ████████████                       50 件
smartwatch           ████████████                       50 件
smartphone            ███████████                       43 件
xiaomi redmi          ████████                          37 件
iphone                ████████                          34 件
samsung galaxy        ████████                          30 件
power bank            ███████                           30 件
```

### 8.3 品牌分布（Top 10）

```
Samsung     ████████████████████████  93 件 (17.7%)
Xiaomi      ████████████████████      77 件 (14.7%)
Apple       █████████████████         66 件 (12.6%)
Motorola    ████████                  32 件 ( 6.1%)
Lenovo      ██████                    23 件 ( 4.4%)
Realme      ████                      15 件 ( 2.9%)
Asus        ████                      15 件 ( 2.9%)
Acer        ███                       12 件 ( 2.3%)
Positivo    ███                       11 件 ( 2.1%)
Microwear   ███                       10 件 ( 1.9%)
其他         ██████████████████████   170 件 (32.4%)
```

### 8.4 商品质量指标

| 指标 | 数值 | 占比 |
|------|------|------|
| 有折扣信息 | 347 件 | 66% |
| 有评分数据 | 496 件 | 94% |
| 铂金卖家 | 294 件 | 56% |
| 免息分期 | 大多数 | — |

### 8.5 字段完整性

```
id          ████████████████████ 100%
title       ████████████████████ 100%
price_brl   ████████████████████ 100%
rating      ██████████████████░░  94%
discount    ████████████████░░░░  66%
brand       ██████████████████░░  ~85%
model       ████████████░░░░░░░░  ~55%
storage     ██████░░░░░░░░░░░░░░  ~30%
ram         █████░░░░░░░░░░░░░░░  ~25%
```

---

## 9. 关键问题与解决方案

### 问题 1：API 返回格式三次变更

```
时间线：
  ── v1 ──────── v2 ──────── v3 (当前) ──▶
  components     results      components
  POLYCARD类型   平铺数组     type=None+item
  
发现方法：
  1. 运行旧脚本 → 0 件商品
  2. 打印 data.keys() → 发现 'results' 不存在
  3. 检查 data['components'][0] → type 为 None，有 'item' 键
  4. 更新提取逻辑

修复代码：
  # 旧：data.get('results', [])
  # 新：
  items = [c['item'] for c in components
           if c.get('type') is None and 'item' in c]
```

### 问题 2：page_size=50 但实际返回 20 条

```
参数 page_size=50  →  paging.limit = 20（服务端忽略客户端配额）

影响：翻页步长必须跟随 paging.limit 动态调整，而非固定步长

修复：
  limit = data.get('paging', {}).get('limit', 20)
  offset += limit   # 而非 offset += 50
```

### 问题 3：免运费字段全为 False

```
原因：tags 数组中 'free_shipping' 来自 item.tags
实际 tags 样本：['interest_free', 'product_ad', 'cart_eligible',
                 'best_seller_candidate']

API 中免运费信息可能在 shipping 子对象而非 tags
当前数据集特点：搜索结果以热门商品为主，多以分期免息（interest_free）
吸引用户，免运费为店铺单独配置字段
```

### 问题 4：某些商品缺少 RAM/存储/屏幕尺寸

```
原因：attributes 数组字段依商品类型不同
  - 手机类：有 "Memória RAM"、"Armazenamento"、"Tamanho da tela"
  - 耳机类：有 "Tipo de conexão"、"Resposta de frequência"
  - 笔记本类：有 "Processador"、"Tamanho da tela"

解决：extract_attrs() 返回完整字典，按字段名按需提取，
     缺失字段默认为空字符串，不影响其他字段
```

---

## 附录：核心代码

### 完整爬取函数

```python
def scrape_query(query, max_items=100):
    url = "https://frontend.mercadolibre.com/sites/MLB/search"
    seen_ids = set()
    products = []
    offset = 0

    while len(products) < max_items:
        params = {'q': query, 'offset': offset,
                  'page_size': 50, 'context': 'android'}
        r = requests.get(url, headers=HEADERS, params=params, timeout=20)
        if r.status_code != 200:
            break
        data = r.json()

        # 当前 API 格式：type=None 的 component 包含 item
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

---

*文档生成于 2026-05-12 | 数据文件：`meli_products.json` | 爬虫：`meli_scraper.py`*
