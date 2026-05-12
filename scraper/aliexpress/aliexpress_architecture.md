# AliExpress 巴西商品数据抓取 — 技术架构文档

> 生成时间：2026-05-12 · 数据集：32,000 个关键词（Phase 1 完成）· 平台：AliExpress 巴西

---

## 目录

1. [项目概述与挑战](#1-项目概述与挑战)
2. [系统架构](#2-系统架构)
3. [技术研究：反爬虫分析](#3-技术研究反爬虫分析)
4. [Phase 1：seo-alphabet 关键词采集](#4-phase-1seo-alphabet-关键词采集)
5. [Phase 2：联盟营销 API 商品搜索](#5-phase-2联盟营销-api-商品搜索)
6. [数据结构](#6-数据结构)
7. [结果](#7-结果)
8. [与 MercadoLibre / Shopee 对比](#8-与-mercadolibre--shopee-对比)

---

## 1. 项目概述与挑战

### 目标

从 AliExpress 巴西站（`pt.aliexpress.com` / `aliexpress.com/bra`）抓取商品数据，包括商品名称、价格、评分、品牌以及商品类目结构。

### 核心挑战

AliExpress 部署了多层反爬虫防御体系：

```
防御层级：

Layer 1: X5/AWSC JavaScript 挑战     ← 每个页面均内嵌 Bot 指纹检测
Layer 2: 登录墙（服务端）             ← 所有商品页面均需登录才能访问
Layer 3: Cookie 绑定                 ← Session token（xman_t、_m_h5_tk）
                                       与 IP/设备绑定，无法跨环境复用
Layer 4: API 鉴权                    ← mtop H5 API 需要基于时间戳的签名
                                       sign = MD5(_m_h5_tk & ts & key & data)
Layer 5: fn/ 接口限制                ← 大多数 /fn/ 路由无论是否鉴权
                                       均返回 ~170 字节错误响应
```

**结论：**
- X5/AWSC：通过 ARMCloud 云手机上的 Yuzu 浏览器（Android WebView）可以绕过
- 登录墙：所有商品内容页均需要已认证会话 —— 无公开路径可绕过
- fn/ 接口：仅 `fn/seo-alphabet/index` 无需登录即可公开访问
- **关键发现**：`seo-alphabet` 接口返回 32,000+ 条热门商品搜索关键词（含类目分类），任何服务器均可直接访问，无需浏览器 Session

---

## 2. 系统架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              研究基础设施                                     │
│                                                                             │
│  ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────────┐   │
│  │  ARMCloud 云手机  │   │   ECS 服务器      │   │    本地 Mac          │   │
│  │  PAD: ACP61H5FU6 │──▶│  101.44.196.235   │   │  aliexpress_         │   │
│  │  Android 13      │   │  mitmproxy 8080   │   │  scraper.py          │   │
│  │  Yuzu 浏览器     │   │  流量日志记录     │   │  联盟 API 调用       │   │
│  └──────────────────┘   └──────────────────┘   └──────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘

Phase 1（关键词采集）：
  Mac ──sshpass SSH──▶ ECS ──curl──▶ aliexpress.com/fn/seo-alphabet/index
                                      （无需鉴权，无 JS 挑战，共 40 页）

Phase 2（商品搜索，需要联盟账号）：
  Mac ──HTTPS──▶ api-sg.aliexpress.com/sync（联盟营销 API，MD5 签名）
```

---

## 3. 技术研究：反爬虫分析

### 3.1 基础设施搭建

ARMCloud 云手机的所有 AliExpress 流量均通过 ECS mitmproxy 代理：

```
ARMCloud 云手机（Android 13，Yuzu 浏览器）
  → Clash 透明代理（iptables CLASH 链）
  → SOCKS5 127.0.0.1:57891
  → ECS 101.44.196.235:8080（mitmproxy）
  → AliExpress 服务器
          ↓ 同步记录流量
  mitmproxy CA 证书已安装为系统信任证书
  日志：/var/log/mitmproxy/flows-2026-05-11.jsonl（2,000+ 条记录）
```

日志格式（扁平 JSON，每条请求一行）：
```json
{"url": "...", "method": "GET", "status_code": 200,
 "content_length": 45000, "request_headers": {...}, "response_headers": {...}}
```

### 3.2 接口状态矩阵

通过分析 Yuzu 浏览器会话中捕获的 mitmproxy 流量得出：

```
❌ 拦截 — 需要登录（重定向至登录页）：
┌──────────────────────────────────────────────────────────────────────┐
│ GET  pt.aliexpress.com/                                               │
│ GET  pt.aliexpress.com/category/phones.html                          │
│ GET  pt.aliexpress.com/w/wholesale-celular.html                      │
│ GET  www.aliexpress.com/popular.html                                  │
│ 所有商品详情页                                                        │
└──────────────────────────────────────────────────────────────────────┘

❌ 拦截 — 返回 170 字节错误（fn/ 内部路由）：
┌──────────────────────────────────────────────────────────────────────┐
│ GET  www.aliexpress.com/fn/recommend-products/...                     │
│ GET  www.aliexpress.com/fn/category-tree/...                         │
│ GET  www.aliexpress.com/fn/deal-products/...                         │
│ [大多数 /fn/ 路由均返回 ~170 字节占位响应]                            │
└──────────────────────────────────────────────────────────────────────┘

❌ 拦截 — mtop H5 API 方法受限：
┌──────────────────────────────────────────────────────────────────────┐
│ POST acs.aliexpress.com/h5/mtop.aliexpress.search.page.do/1.0/       │
│      → "API not found"（仅限移动端 App）                             │
│ POST acs.aliexpress.com/h5/mtop.ae.category.recommend.products/1.0/  │
│      → "API not found"                                               │
└──────────────────────────────────────────────────────────────────────┘

✅ 可访问（无需鉴权）：
┌──────────────────────────────────────────────────────────────────────┐
│ GET  www.aliexpress.com/fn/seo-alphabet/index                         │
│      ?channel=popular&pageNo=N&pageVersion=1d83f91d7b218221cecdf0e9548cad9a │
│      → 45KB JSON · 每页 800 个关键词 · 共 40 页 · 无需登录           │
│                                                                      │
│ POST acs.aliexpress.com/h5/mtop.ae.cookie.render/1.0/               │
│      → 设置 _m_h5_tk session token（工具接口，不返回商品数据）       │
└──────────────────────────────────────────────────────────────────────┘
```

### 3.3 X5/AWSC JavaScript 挑战

```
X5 Bot 挑战机制：
  - AliExpress 每个页面均内嵌指纹检测 JS
  - 检测对象：headless Chrome、服务端渲染、自动化操作行为
  - Yuzu 浏览器（Android WebView）可通过 X5 检测，返回真实 Session Cookie
  - 直接使用 curl/requests 会触发 X5 → 收到挑战 HTML，而非商品数据

登录墙（独立于 X5）：
  - 即使通过 X5 挑战，所有商品内容页仍然会重定向到登录页
  - 登录要求在服务端实现，无法绕过
  - 从 Yuzu 浏览器捕获的 xman_t Cookie 有效，但与页面会话绑定
  - 在其他 IP/设备上复用 xman_t → 触发登录重定向
```

### 3.4 mtop H5 API — Token 体系

`acs.aliexpress.com/h5/{method}` 接口系统需要基于时间戳的签名：

```
Step 1: 获取 _m_h5_tk token
  POST acs.aliexpress.com/h5/mtop.ae.cookie.render/1.0/
  → 响应设置 Cookie：_m_h5_tk={40位token}_{时间戳}

Step 2: 计算 API 调用签名
  token_hash, ts = cookie 值按 '_' 分割
  sign = MD5(f"{token_hash}&{timestamp}&{app_key}&{json.dumps(data)}")

Step 3: 调用 API
  POST acs.aliexpress.com/h5/{method}/1.0/
  ?appKey=12574478&t={timestamp}&sign={md5}&jsv=2.6.2

结果：搜索/推荐方法 → "API not found"（仅限移动端 App）
      只有工具类方法（cookie render、静态配置）可以成功调用
```

### 3.5 Yuzu 浏览器捕获的 Cookie

```http
Cookie: xman_t=ReWmFUK9Kwo/0Kh+G0qHGkIqEROr5/j30C2BU/3vnJJoihivRvoT9n5kZnXctOs0
        cna=IBaHIl9Q4l0CAWUsxOs/sXOO
        aep_usuc_f=site=bra&c_tp=BRL&region=BR&b_locale=en_US&ae_u_p_s=2
        _m_h5_tk=4da88a9871219559cc93f706eb4d9875_1778400682766
```

这些 Cookie 是必要条件但非充分条件 —— 从不同 IP 复用会触发登录重定向。访问商品页面需要绑定到手机 IP 的有效 AliExpress 会话。

---

## 4. Phase 1：seo-alphabet 关键词采集

### 4.1 发现过程

`fn/seo-alphabet/index` 是 AliExpress 内部的 SEO 交叉链接系统接口，为 AliExpress 热搜词页面提供数据，返回按类目组织的分页热门商品搜索关键词列表。

**关键特性：**
- 无需鉴权
- 无 JavaScript 挑战（可通过 curl/requests 直接访问）
- 任何服务器 IP 均可访问（已在 ECS 101.44.196.235 上验证）
- 共 40 页 × ~800 个关键词 ≈ 32,000 个唯一关键词
- 每个关键词包含类目分类及批发搜索 URL

### 4.2 请求格式

```http
GET /fn/seo-alphabet/index?channel=popular&pageNo=1&pageVersion=1d83f91d7b218221cecdf0e9548cad9a HTTP/1.1
Host: www.aliexpress.com
Accept: application/json, */*
Accept-Language: pt-BR,pt;q=0.9
Referer: https://www.aliexpress.com/
```

**无需 Cookie、User-Agent 或鉴权 Token。**

### 4.3 响应数据结构

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
                }
              ]
            }
          ]
        }
      }
    }
  }
}
```

### 4.4 为什么用 ECS 直连而非 ARMCloud syncCmd

初始实现通过 ARMCloud `syncCmd`（云手机 shell）转发请求：
- `syncCmd` 有约 **45KB 的输出大小限制** —— seo-alphabet 响应（每页 45KB JSON）会被截断
- 基于文件的方案（写入手机文件后再 `cat`）同样返回空内容
- **解决方案**：通过 SSH 直接在 ECS 服务器上运行 curl —— 无输出截断，无需手机代理

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

---

## 5. Phase 2：联盟营销 API 商品搜索

### 5.1 概述

AliExpress 提供免费的联盟营销 API，可返回含价格、评分、佣金率的真实商品数据。无需浏览器 Session，使用 MD5 签名的 API 密钥即可调用。

**注册地址**：[portals.aliexpress.com](https://portals.aliexpress.com/) → Dashboard → Tools → API → Create App（免费）

### 5.2 签名算法

```python
def affiliate_sign(params, app_secret):
    sign_str = app_secret
    for k in sorted(params.keys()):   # 按 key 字母序排列
        sign_str += k + str(params[k])
    sign_str += app_secret
    return hashlib.md5(sign_str.encode('utf-8')).hexdigest().upper()
```

格式：`app_secret + "app_key" + app_key值 + "keywords" + keyword值 + ... + app_secret`

### 5.3 可用方法

```
aliexpress.affiliate.hotproduct.query   ← 全球热销商品
aliexpress.affiliate.product.query      ← 按关键词搜索（配合 seo-alphabet 关键词使用）
aliexpress.affiliate.featuredpromo.get  ← 促销商品
```

### 5.4 关键词搜索请求示例

```python
params = {
    'method': 'aliexpress.affiliate.product.query',
    'keywords': 'celular',          # 来自 seo-alphabet 关键词列表
    'page_no': '1',
    'page_size': '50',
    'sort': 'SALE_PRICE_ASC',
    'target_currency': 'BRL',
    'target_language': 'PT',
    'ship_to_country': 'BR',
    'fields': 'commission_rate,sale_price,original_price,discount,product_title,'
              'product_main_image_url,evaluate_rate,lastest_volume,category_id,'
              'product_url,shop_id,seller_id',
}
```

---

## 6. 数据结构

### 6.1 aliexpress_keywords.json

```json
{
  "generated_at": "2026-05-11T...",
  "total_keywords": 32000,
  "categories": {
    "Consumer Electronics": ["xiaomi redmi note 13", "samsung galaxy s24", ...],
    ...
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

### 6.2 商品字段说明（Phase 2 联盟 API）

| 字段 | 类型 | 说明 |
|------|------|------|
| `title` | str | 完整商品名称（PT 语言） |
| `price_brl` | float | 售价（巴西雷亚尔） |
| `original_price_brl` | float | 原价（折扣前） |
| `discount` | str | 折扣百分比，如 "30%" |
| `rating` | str | 好评率 0–100，如 "97" |
| `sales` | int | 近期销量 |
| `category_id` | str | AliExpress 内部类目 ID |
| `image` | str | 商品主图 URL |
| `url` | str | 商品详情页 URL |
| `shop_id` | str | 卖家店铺 ID |
| `commission_rate` | str | 联盟佣金率，如 "4.00%" |

---

## 7. 结果

### 7.1 Phase 1 — 关键词类目体系

| 指标 | 数值 |
|------|------|
| 唯一关键词总数 | **32,000** |
| AliExpress 服务端总量 | ~60,000 |
| 已抓取页数 | 40 / 40 |
| 类目数量 | **33** |
| 采集方式 | ECS SSH + 直连 curl |
| 是否需要鉴权 | 否 |

**各类目关键词数量（前 11 名）：**

| 类目 | 关键词数 |
|------|---------|
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

### 7.2 Phase 2 — 联盟 API（待配置凭证）

Phase 2 需要在 portals.aliexpress.com 注册免费联盟 API 应用。
配置完成后，抓取器可采集：
- 每个关键词查询最多 50 条商品
- 每次运行 150 条热销商品（3 页 × 50 条）
- 完整价格、折扣、评分、佣金数据
- 商品图片和店铺 ID

使用 Phase 1 采集的 1,027 个手机/通信类关键词作为搜索词，可获得数千条含完整价格数据的商品记录。

---

## 8. 与 MercadoLibre / Shopee 对比

```
                    MercadoLibre          Shopee               AliExpress（本方案）
                    ─────────────         ──────────────        ────────────────────────
数据来源             移动端搜索 API         Facebook Bot SSR      seo-alphabet + 联盟 API
接口端点             frontend.meli.com     shopee.com.br HTML    AliExpress fn/ + API
鉴权方式             Bearer Token（APK）   无需（Bot SSR）       Phase1: 无；Phase2: API Key
反爬虫绕过           静态 APK Token        facebookexternalhit   seo-alphabet: 无 Bot 检测；
                                           User-Agent            联盟 API: 签名密钥
响应格式             JSON                  HTML → ld+json        Phase1: JSON；Phase2: JSON
价格覆盖率           100%                  10.9%（224/2059）     Phase1: 0%；Phase2: ~100%
总商品数             524（10 次查询）       2,059（~540 页）      32,000 关键词；商品需凭证
数据丰富度           高：评分、卖家、       中：评分、品牌         高：价格、折扣、
                     品牌、型号、存储       （每页仅 1 条）        评分、佣金
类目精度             高（关键词搜索）       中（宽泛类目）         高（seo-alphabet 类目）
吞吐量               每请求 20–28 条       每页 10–20 条含价格    每次查询 50 条/关键词
```

**核心差异**：AliExpress 是唯一需要凭证才能获取商品价格数据的平台。seo-alphabet 是唯一可公开访问的数据源，提供优质的关键词类目体系但无商品价格。联盟 API 在注册后可完美弥补这一缺口。

---

## 附录：爬虫配置说明

```
Phase 1：
  ECS_HOST = '101.44.196.235'     通过 SSH 在 ECS 上执行 seo-alphabet 抓取
  KEYWORDS_FILE = aliexpress_keywords.json   缓存文件（force_refresh=True 可强制重采）

Phase 2（注册后填入）：
  AFFILIATE_APP_KEY = ''
  AFFILIATE_APP_SECRET = ''
  AFFILIATE_API_URL = 'https://api-sg.aliexpress.com/sync'

运行方式：
  python3 aliexpress_scraper.py          # 仅 Phase 1（从缓存加载或重新采集）
  AFFILIATE_APP_KEY=... python3 ...      # Phase 1 + Phase 2
```

### seo-alphabet pageVersion 说明

```
pageVersion=1d83f91d7b218221cecdf0e9548cad9a
```
此版本字符串目前稳定 —— 在全部 40 页及多次采集运行中保持一致。如果接口停止返回数据，可通过抓包 `www.aliexpress.com/popular.html` 的浏览器请求检查该版本是否已更换。

---

*生成时间：2026-05-12 | 数据文件：`aliexpress_keywords.json`、`aliexpress_products.json` | 爬虫：`aliexpress_scraper.py`*
*Phase 1 方式：ECS SSH + seo-alphabet 直连（无需鉴权）| Phase 2：联盟营销 API（portals.aliexpress.com）*
