#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
静态博客生成器 —— 赚钱App大全
零第三方依赖，仅用 Python 标准库。读取 data/*.json，输出纯静态站点到 site/。

用法：
    python scripts/build.py

会生成：
    site/index.html              首页
    site/posts/<slug>/index.html 文章详情
    site/tools/index.html        赚钱App清单（分类总入口）
    site/tools/<slug>/index.html 统一分类页（App + 文章）
    site/ranking/index.html      可筛选排行榜
    site/about/index.html        关于
    site/search/index.html       搜索
    site/404.html
    site/sitemap.xml / robots.txt / search-index.json
"""
import json
import html
import re
import shutil
import hashlib
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SITE = ROOT / "site"
STATIC = ROOT / "static"  # 站长验证等需长期驻留根目录的静态文件

# ----------------------------------------------------------------------------
# 数据加载
# ----------------------------------------------------------------------------
def load_json(name, default=None):
    path = DATA / name
    if not path.exists():
        if default is not None:
            return default
        raise FileNotFoundError(f"缺少数据文件：{path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


SITE_CFG = load_json("site.json")
CATEGORIES = load_json("categories.json")
AFFILIATES = load_json("affiliates.json")
ARTICLES = load_json("articles.json")
MEDIA = load_json("app_media.json", {"trusted_screenshots": [], "info": {}})

CAT_MAP = {c["slug"]: c for c in CATEGORIES}
AFF_MAP = {a["id"]: a for a in AFFILIATES}
TRUSTED_SHOTS = set(MEDIA.get("trusted_screenshots", []))
APP_INFO = MEDIA.get("info", {})


def asset_ver(rel):
    """按静态文件内容生成短版本号，内容变更即换 URL，彻底避免浏览器缓存旧样式。"""
    p = SITE / rel
    try:
        return hashlib.md5(p.read_bytes()).hexdigest()[:8]
    except Exception:
        return "1"

CSS_VER = asset_ver("assets/css/style.css")
JS_VER = asset_ver("assets/js/main.js")


# ----------------------------------------------------------------------------
# 维度兜底：新增 App 若未打标，给合理默认值，保证排行榜/分类页不漏项
# ----------------------------------------------------------------------------
def ensure_dims(a):
    """为缺少筛选维度的 App 补默认值（幂等），并计算综合分。"""
    if "withdraw" not in a or not isinstance(a.get("withdraw"), dict):
        blob = " ".join([a.get("commission", ""), a.get("tag", "")] + a.get("pros", []))
        if any(k in blob for k in ["秒到", "秒提", "一单一结", "秒结算"]):
            a["withdraw"] = {"label": "秒到", "days": 0.5}
        elif any(k in blob for k in ["满10", "10元提现"]):
            a["withdraw"] = {"label": "1-3天", "days": 3}
        else:
            a["withdraw"] = {"label": "当天", "days": 1}
    if "price" not in a or not isinstance(a.get("price"), dict):
        a["price"] = {"label": "中", "level": 2}
    if "audience" not in a or not isinstance(a.get("audience"), list):
        a["audience"] = ["所有人"]
    if "platform" not in a:
        a["platform"] = "android"
    a["stopped"] = bool(a.get("stopped")) or "停运" in a.get("name", "") or "停运" in a.get("type", "")
    # 综合分：评分权重最高，其次单价、提现速度（days 越小越快），停运沉底
    try:
        w = float(a["withdraw"].get("days", 1))
        p = int(a["price"].get("level", 2))
        r = float(a.get("rating", 4))
        a["score"] = round(r * 2 + p * 1.5 + 5 / (w + 0.5) - (10 if a["stopped"] else 0), 2)
    except Exception:
        a["score"] = 0
    return a


for _a in AFFILIATES:
    ensure_dims(_a)
AFF_MAP = {a["id"]: a for a in AFFILIATES}


# ----------------------------------------------------------------------------
# 工具函数
# ----------------------------------------------------------------------------
def esc(s):
    return html.escape(str(s), quote=True)


def fmt_date(s):
    try:
        d = datetime.strptime(s, "%Y-%m-%d")
        return f"{d.year}年{d.month}月{d.day}日"
    except Exception:
        return s


def fmt_num(n):
    try:
        n = int(n)
    except Exception:
        return str(n)
    if n >= 10000:
        return f"{n/10000:.1f}万"
    return str(n)


def sort_articles(articles):
    return sorted(articles, key=lambda a: a.get("date", ""), reverse=True)


def cat_of(article):
    return CAT_MAP.get(article.get("category"), {
        "slug": article.get("category", ""),
        "name": article.get("category", "未分类"),
        "color": "#64748b",
        "icon": "📁",
    })


def url_of(article):
    return f"/posts/{article['slug']}/"


def fmt_stars(rating):
    try:
        r = float(rating)
    except Exception:
        r = 0
    full = int(round(r))
    return "⭐" * full


# ----------------------------------------------------------------------------
# 轻量 Markdown 渲染（支持标题/段落/列表/引用/代码块/加粗/链接/联盟卡片）
# ----------------------------------------------------------------------------
def inline_md(text):
    text = html.escape(text, quote=False)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)",
                  r'<a href="\2" target="_blank" rel="noopener">\1</a>', text)
    return text


def render_affiliate_card(aid):
    a = AFF_MAP.get(aid.strip())
    if not a:
        return ""
    pros = "".join(f"<li>{esc(p)}</li>" for p in a.get("pros", []))
    return f"""
    <aside class="aff-card" style="--aff-color:{esc(a.get('color','#4f46e5'))}">
      <div class="aff-head">
        <div class="aff-icon">{esc(a.get('emoji','💡'))}</div>
        <div class="aff-headtext">
          <div class="aff-name">{esc(a.get('name'))} <span class="aff-tag">{esc(a.get('tag',''))}</span></div>
          <div class="aff-meta">{fmt_stars(a.get('rating'))} <span>{esc(a.get('rating'))}</span> · {esc(a.get('type',''))}</div>
        </div>
      </div>
      <div class="aff-bonus">🎁 {esc(a.get('commission',''))}</div>
      <ul class="aff-pros">{pros}</ul>
      <a class="aff-cta" href="{esc(a.get('url'))}" target="_blank" rel="sponsored noopener">下载试用 →</a>
      <span class="aff-ad">广告 · 通过此链接注册我们可能获得佣金</span>
    </aside>"""


AFF_RE = re.compile(r"^\[\[affiliate:([^\]]+)\]\]$")
INCOME_RE = re.compile(r"^\[\[income:([^\]]+)\]\]$")
APPINFO_RE = re.compile(r"^\[\[appinfo:([^\]]+)\]\]$")
GALLERY_RE = re.compile(r"^\[\[gallery:([^\]]+)\]\]$")


def render_app_info(aid):
    """官方信息卡：图标 + 联网核实的真实运营信息。每款内容不同。"""
    a = AFF_MAP.get(aid.strip())
    info = APP_INFO.get(aid.strip(), {})
    if not a:
        return ""
    trusted = aid.strip() in TRUSTED_SHOTS
    icon = f"/assets/apps/{aid.strip()}/icon.webp" if trusted else ""
    icon_html = (f'<img class="ai-logo" src="{icon}" alt="{esc(a.get("name"))}图标" loading="lazy">'
                 if icon else f'<div class="ai-logo ai-logo-emoji">{esc(a.get("emoji","📱"))}</div>')
    c = cat_of({"category": a.get("category")})
    rows = []
    if info.get("company"):
        rows.append(("运营主体", info["company"]))
    if info.get("since"):
        rows.append(("上线/背景", info["since"]))
    rows.append(("赚钱方式", info.get("gameplay", a.get("type", ""))))
    rows.append(("提现规则", info.get("withdraw", a.get("commission", ""))))
    rows_html = "".join(
        f'<div class="ai-row"><span class="ai-k">{esc(k)}</span><span class="ai-v">{esc(v)}</span></div>'
        for k, v in rows
    )
    source = "应用宝官方图标 · 运营信息经公开资料核实" if trusted else "运营信息经公开资料核实"
    return f"""
    <section class="app-info" style="--aff-color:{esc(a.get('color','#4f46e5'))}">
      <div class="ai-head">{icon_html}
        <div class="ai-title">
          <div class="ai-name">{esc(a.get('name'))}</div>
          <div class="ai-cat">{esc(c['icon'])} {esc(c['name'])} · {esc(a.get('type',''))}</div>
        </div>
        <div class="ai-badge">{'✓ 官方图' if trusted else '资料卡'}</div>
      </div>
      <p class="ai-hook">{esc(info.get('hook', a.get('commission','')))}</p>
      <div class="ai-rows">{rows_html}</div>
      <div class="ai-source">📌 {source}，具体以 App 内为准</div>
    </section>"""


def render_gallery(aid):
    """真实截图画廊：优先用网络抓取的真实界面图，回退到应用宝官方截图；无图则返回空。"""
    aid = aid.strip()
    a = AFF_MAP.get(aid)
    if not a:
        return ""
    folder = SITE / "assets" / "apps" / aid
    # 优先网络抓图（web1..3），其次应用宝截图（shot1..3）
    shots = [f"/assets/apps/{aid}/web{i}.webp" for i in range(1, 4) if (folder / f"web{i}.webp").exists()]
    source = "来自公开的软件介绍页与测评文章，经人工核对为对应 App 的真实界面"
    if not shots and aid in TRUSTED_SHOTS:
        shots = [f"/assets/apps/{aid}/shot{i}.webp" for i in range(1, 4) if (folder / f"shot{i}.webp").exists()]
        source = "来自应用宝官方收录（开发商主体已核对）"
    if not shots:
        return ""
    imgs = "".join(
        f'<figure class="gal-item"><img src="{src}" alt="{esc(a.get("name"))}界面截图 {i}" loading="lazy"></figure>'
        for i, src in enumerate(shots, 1)
    )
    return f"""
    <section class="app-gallery">
      <h3 class="gal-title">📱 {esc(a.get('name'))} 真实界面截图</h3>
      <p class="gal-note">以下截图{source}，供你了解 App 实际界面。</p>
      <div class="gal-track">{imgs}</div>
    </section>"""


def render_income_shot(aid):
    """收益界面示意图：按 App 真实维度数据生成，明确标注非真实凭证。"""
    a = AFF_MAP.get(aid.strip())
    if not a:
        return ""
    pr = a.get("price", {})
    wd = a.get("withdraw", {})
    level = pr.get("level", 2)
    # 按单价档位生成示例金额（示意，非真实收益）
    today = {1: "6.5", 2: "15.0", 3: "32.0"}.get(level, "15.0")
    month = {1: "约 120", 2: "约 320", 3: "约 680"}.get(level, "约 320")
    wd_label = WD_LABEL.get(wd.get("label"), wd.get("label", "当天"))
    tasks = {1: "8", 2: "14", 3: "22"}.get(level, "14")
    return f"""
    <figure class="income-shot" style="--aff-color:{esc(a.get('color','#4f46e5'))}">
      <div class="ishot-phone">
        <div class="ishot-bar"><span>9:41</span><span>●●● ▰</span></div>
        <div class="ishot-app">{esc(a.get('emoji','📱'))} {esc(a.get('name'))} · 我的收益</div>
        <div class="ishot-balance"><span>累计收益（元）</span><b>{month}</b></div>
        <div class="ishot-grid">
          <div><span>今日收益</span><b>¥{today}</b></div>
          <div><span>今日任务</span><b>{tasks} 单</b></div>
          <div><span>提现状态</span><b>{esc(wd_label)}</b></div>
          <div><span>起提门槛</span><b>{esc(a.get('commission',''))}</b></div>
        </div>
        <div class="ishot-btn">立即提现</div>
      </div>
      <figcaption>⚠️ 收益界面示意 · 数字按平台单价水平示例，非真实收款凭证，实际收益因人而异</figcaption>
    </figure>"""


def render_markdown(md):
    lines = md.split("\n")
    out = []
    i, n = 0, len(lines)
    while i < n:
        s = lines[i].strip()
        if not s:
            i += 1
            continue
        # 代码块
        if s.startswith("```"):
            i += 1
            buf = []
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(html.escape(lines[i]))
                i += 1
            i += 1
            out.append("<pre><code>" + "\n".join(buf) + "</code></pre>")
            continue
        # 联盟卡片
        m = AFF_RE.match(s)
        if m:
            out.append(render_affiliate_card(m.group(1)))
            i += 1
            continue
        # 收益截图示意
        m = INCOME_RE.match(s)
        if m:
            out.append(render_income_shot(m.group(1)))
            i += 1
            continue
        # 官方信息卡（联网核实资料）
        m = APPINFO_RE.match(s)
        if m:
            out.append(render_app_info(m.group(1)))
            i += 1
            continue
        # 真实截图画廊（仅开发商核对通过的 App）
        m = GALLERY_RE.match(s)
        if m:
            out.append(render_gallery(m.group(1)))
            i += 1
            continue
        # 标题
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            lvl = len(m.group(1))
            txt = inline_md(m.group(2))
            anchor = re.sub(r"[^\w\u4e00-\u9fa5]+", "-", m.group(2)).strip("-")[:24]
            out.append(f'<h{lvl} id="{esc(anchor)}">{txt}</h{lvl}>')
            i += 1
            continue
        # 引用
        if s.startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip(">").strip())
                i += 1
            out.append("<blockquote>" + inline_md(" ".join(buf)) + "</blockquote>")
            continue
        # 无序列表
        if re.match(r"^[-*]\s+", s):
            buf = []
            while i < n and re.match(r"^[-*]\s+", lines[i].strip()):
                buf.append("<li>" + inline_md(re.sub(r"^[-*]\s+", "", lines[i].strip())) + "</li>")
                i += 1
            out.append("<ul>" + "".join(buf) + "</ul>")
            continue
        # 有序列表
        if re.match(r"^\d+\.\s+", s):
            buf = []
            while i < n and re.match(r"^\d+\.\s+", lines[i].strip()):
                buf.append("<li>" + inline_md(re.sub(r"^\d+\.\s+", "", lines[i].strip())) + "</li>")
                i += 1
            out.append("<ol>" + "".join(buf) + "</ol>")
            continue
        # 段落
        buf = [s]
        i += 1
        while i < n:
            ns = lines[i].strip()
            if not ns:
                break
            if (ns.startswith("```") or ns.startswith(">") or AFF_RE.match(ns) or INCOME_RE.match(ns)
                    or APPINFO_RE.match(ns) or GALLERY_RE.match(ns)
                    or re.match(r"^#{1,6}\s", ns) or re.match(r"^[-*]\s+", ns)
                    or re.match(r"^\d+\.\s+", ns)):
                break
            buf.append(ns)
            i += 1
        out.append("<p>" + inline_md(" ".join(buf)) + "</p>")
    return "\n".join(out)


def build_toc(md):
    toc = []
    for line in md.split("\n"):
        m = re.match(r"^(##|###)\s+(.*)$", line.strip())
        if m:
            lvl = 2 if len(m.group(1)) == 2 else 3
            txt = m.group(2)
            anchor = re.sub(r"[^\w\u4e00-\u9fa5]+", "-", txt).strip("-")[:24]
            toc.append((lvl, txt, anchor))
    if not toc:
        return ""
    items = "".join(
        f'<a class="toc-l{lvl}" href="#{esc(anchor)}">{esc(txt)}</a>'
        for lvl, txt, anchor in toc
    )
    return f'<nav class="toc"><div class="toc-title">📑 本文目录</div>{items}</nav>'


# ----------------------------------------------------------------------------
# 页面片段
# ----------------------------------------------------------------------------
def header_html(active=""):
    nav = ""
    for item in SITE_CFG.get("nav", []):
        cls = " active" if item["url"] == active else ""
        nav += f'<a class="nav-link{cls}" href="{esc(item["url"])}">{esc(item["label"])}</a>'
    return f"""
<header class="site-header">
  <div class="container header-inner">
    <a class="brand" href="/">
      <span class="brand-mark">📱</span>
      <span class="brand-text">{esc(SITE_CFG['name'])}<small>{esc(SITE_CFG.get('name_en',''))}</small></span>
    </a>
    <nav class="nav">{nav}</nav>
    <div class="header-actions">
      <a class="icon-btn" href="/search/" aria-label="搜索">🔍</a>
      <a class="btn btn-sm btn-primary" href="/tools/">找App →</a>
    </div>
  </div>
</header>"""


def footer_html():
    nav = "".join(
        f'<a href="{esc(i["url"])}">{esc(i["label"])}</a>'
        for i in SITE_CFG.get("nav", [])
    )
    year = datetime.now().year
    return f"""
<footer class="site-footer">
  <div class="container footer-grid">
    <div class="footer-brand">
      <div class="brand"><span class="brand-mark">📱</span><span class="brand-text">{esc(SITE_CFG['name'])}</span></div>
      <p>{esc(SITE_CFG.get('description',''))}</p>
    </div>
    <div class="footer-col"><h4>站点导航</h4>{nav}</div>
    <div class="footer-col"><h4>热门分类</h4>
      {''.join(f'<a href="/tools/{esc(c["slug"])}/">{esc(c["icon"])} {esc(c["name"])}</a>' for c in CATEGORIES[:5])}
    </div>
    <div class="footer-col"><h4>免责声明</h4>
      <a href="/about/#affiliate">联盟披露</a>
      <a href="/about/#disclaimer">内容免责</a>
      <a href="/about/#contact">联系我们</a>
    </div>
  </div>
  <div class="container footer-bottom">
    <span>© {year} {esc(SITE_CFG['name'])} · 保留所有权利</span>
    <span>部分链接为联盟链接，我们可能获得佣金，但不影响你的价格。</span>
  </div>
</footer>"""


def layout(title, description, body, active="", canonical="/", og_emoji="📱"):
    analytics = ""
    aid = SITE_CFG.get("analytics_id", "")
    if aid:
        analytics = f"""<script defer src="https://umami.example.com/script.js" data-website-id="{esc(aid)}"></script>"""
    return f"""<!DOCTYPE html>
<html lang="{esc(SITE_CFG.get('lang','zh-CN'))}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(title)} | {esc(SITE_CFG['name'])}</title>
<meta name="description" content="{esc(description)}">
<meta name="author" content="{esc(SITE_CFG.get('author',''))}">
<link rel="canonical" href="{esc(SITE_CFG.get('domain','').rstrip('/') + canonical)}">
<meta property="og:type" content="website">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:url" content="{esc(SITE_CFG.get('domain','').rstrip('/') + canonical)}">
<meta property="og:image" content="{esc(og_emoji)}">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>📱</text></svg>">
<link rel="stylesheet" href="/assets/css/style.css?v={CSS_VER}">
{analytics}
<script type="application/ld+json">
{{"@context":"https://schema.org","@type":"WebSite","name":"{esc(SITE_CFG['name'])}","url":"{esc(SITE_CFG.get('domain',''))}"}}
</script>
</head>
<body>
{header_html(active)}
<main>{body}</main>
{footer_html()}
<button class="backtop" id="backtop" aria-label="返回顶部">↑</button>
<script src="/assets/js/main.js?v={JS_VER}"></script>
</body>
</html>"""


def article_card(a, compact=False):
    c = cat_of(a)
    cls = "post-card compact" if compact else "post-card"
    return f"""
<a class="{cls}" href="{esc(url_of(a))}" style="--cat-color:{esc(c['color'])}">
  <div class="post-cover" style="--cover-color:{esc(a.get('color', c['color']))}"><span>{esc(a.get('emoji','📄'))}</span></div>
  <div class="post-body">
    <div class="post-meta"><span class="cat-pill">{esc(c['icon'])} {esc(c['name'])}</span><time>{fmt_date(a.get('date'))}</time></div>
    <h3>{esc(a.get('title'))}</h3>
    <p>{esc(a.get('excerpt'))}</p>
    <div class="post-foot"><span>⏱ {esc(a.get('read_time',5))} 分钟</span><span>👀 {fmt_num(a.get('views',0))}</span></div>
  </div>
</a>"""


def article_list_item(a, index=None):
    """列表式文章条目：左侧彩色缩略块(含序号角标)，右侧标题+摘要+元信息。用于首页精选。"""
    c = cat_of(a)
    num = f'<span class="pli-num">{index:02d}</span>' if index else ""
    return f"""
<a class="post-list-item" href="{esc(url_of(a))}" style="--cat-color:{esc(c['color'])}">
  <div class="pli-thumb">{num}<span class="pli-emoji">{esc(a.get('emoji') or c.get('icon','📄'))}</span></div>
  <div class="pli-body">
    <div class="pli-meta"><span class="cat-pill">{esc(c['icon'])} {esc(c['name'])}</span><time>{fmt_date(a.get('date'))}</time></div>
    <h3>{esc(a.get('title'))}</h3>
    <p>{esc(a.get('excerpt'))}</p>
    <div class="pli-foot"><span>⏱ {esc(a.get('read_time',5))} 分钟阅读</span><i class="pli-sep"></i><span>👀 {fmt_num(a.get('views',0))} 阅读</span><span class="pli-go">阅读全文 →</span></div>
  </div>
</a>"""


def aff_card(a, large=False):
    cls = "aff-item large" if large else "aff-item"
    return f"""
<div class="{cls}" style="--aff-color:{esc(a.get('color','#4f46e5'))}">
  <div class="aff-item-icon">{esc(a.get('emoji','💡'))}</div>
  <div class="aff-item-body">
    <div class="aff-item-title">{esc(a.get('name'))} <span class="mini-tag">{esc(a.get('tag',''))}</span></div>
    <div class="aff-item-desc">{esc(a.get('commission',''))}</div>
  </div>
  <a class="aff-item-btn" href="{esc(a.get('url'))}" target="_blank" rel="sponsored noopener">去试试</a>
</div>"""


def newsletter_html():
    nl = SITE_CFG.get("newsletter", {})
    return f"""
<section class="newsletter">
  <div class="container newsletter-inner">
    <div class="newsletter-text">
      <h2>✉️ {esc(nl.get('title',''))}</h2>
      <p>{esc(nl.get('subtitle',''))}</p>
    </div>
    <form class="newsletter-form" id="subscribe-form">
      <input type="email" placeholder="{esc(nl.get('placeholder','输入邮箱'))}" required>
      <button class="btn btn-primary" type="submit">{esc(nl.get('button','免费订阅'))}</button>
    </form>
    <div class="newsletter-note">{esc(nl.get('note',''))}</div>
  </div>
</section>"""


# ----------------------------------------------------------------------------
# 各页面构建
# ----------------------------------------------------------------------------
def build_home():
    arts = sort_articles(ARTICLES)
    featured = [a for a in arts if a.get("featured")][:3] or arts[:3]
    latest = arts[:6]
    top_aff = [a for a in AFFILIATES if a.get("featured")][:3] or AFFILIATES[:3]
    hero = SITE_CFG["hero"]

    # hero 标题支持 \n 换行
    hero_title = esc(hero["title"]).replace("\\n", "<br>").replace("\n", "<br>")

    stats = "".join(
        f'<div class="stat"><div class="stat-value">{esc(s["value"])}</div><div class="stat-label">{esc(s["label"])}</div></div>'
        for s in SITE_CFG.get("stats", [])
    )
    featured_html = "".join(article_list_item(a, i) for i, a in enumerate(featured, 1))
    latest_html = "".join(article_card(a, compact=True) for a in latest)
    aff_html = "".join(aff_card(a) for a in top_aff)
    cat_html = "".join(
        f'<a class="cat-card" href="/tools/{esc(c["slug"])}/" style="--cat-color:{esc(c["color"])}">'
        f'<div class="cat-icon">{esc(c["icon"])}</div><h3>{esc(c["name"])}</h3>'
        f'<p>{esc(c["description"])}</p><span>{sum(1 for a in arts if a.get("category")==c["slug"])} 篇测评 →</span></a>'
        for c in CATEGORIES
    )

    body = f"""
<section class="hero">
  <div class="hero-bg"><span></span><span></span><span></span></div>
  <div class="container hero-inner">
    <div class="hero-content">
      <div class="hero-badge">✨ {esc(hero['badge'])}</div>
      <h1>{hero_title}</h1>
      <p class="hero-sub">{esc(hero['subtitle'])}</p>
      <div class="hero-actions">
        <a class="btn btn-primary btn-lg" href="{esc(hero['primary_url'])}">{esc(hero['primary_cta'])} →</a>
        <a class="btn btn-ghost btn-lg" href="/ranking/">🏆 看排行榜</a>
      </div>
      <div class="hero-trust">🔒 完全免费 · 无套路 · 只推能提现的App</div>
    </div>
    <div class="hero-art">
      <div class="float-card fc1">🎵 <b>刷视频赚钱</b><br><small>金币当天提现</small></div>
      <div class="float-card fc2">📖 <b>看小说躺赚</b><br><small>听书也算时长</small></div>
      <div class="float-card fc3">🐟 <b>手机卖出单</b><br><small>零成本开店</small></div>
      <div class="hero-orb">📱</div>
    </div>
  </div>
  <div class="container">{f'<div class="stats-bar">{stats}</div>'}</div>
</section>

<section class="section" id="featured">
  <div class="container">
    <div class="section-head"><div><span class="kicker">编辑精选</span><h2>🔥 值得先看的赚钱测评</h2></div><a class="more" href="/tools/">全部文章 →</a></div>
    <div class="post-list">{featured_html}</div>
  </div>
</section>

<section class="section section-alt" id="projects">
  <div class="container">
    <div class="section-head"><div><span class="kicker">提现实测</span><h2>💎 靠谱的手机赚钱App</h2></div><a class="more" href="/tools/">查看全部 →</a></div>
    <div class="aff-grid">{aff_html}</div>
    <p class="aff-disclosure">以上为编辑精选平台，部分为联盟链接，我们可能获得佣金，不影响你的注册与使用。</p>
  </div>
</section>

<section class="section section-alt">
  <div class="container"><div class="quick-entry">
    <a class="qe-card qe-rank" href="/ranking/">
      <div class="qe-icon">🏆</div><div><h3>排行榜 · 按需筛选</h3>
      <p>按提现速度、单价、适合人群一筛到底，快速找到最适合你的App。</p></div><span class="qe-go">去筛选 →</span>
    </a>
    <a class="qe-card qe-plat" href="/tools/">
      <div class="qe-icon">🗂️</div><div><h3>按类型挑App</h3>
      <p>任务赚钱、问卷赚钱、看视频、游戏试玩……7 大分类一次看全。</p></div><span class="qe-go">去看看 →</span>
    </a>
  </div></div>
</section>

<section class="section" id="categories">
  <div class="container">
    <div class="section-head"><div><span class="kicker">按方向找</span><h2>🧭 你想从哪个方向开始？</h2></div></div>
    <div class="cat-grid">{cat_html}</div>
  </div>
</section>

<section class="section section-alt" id="latest">
  <div class="container">
    <div class="section-head"><div><span class="kicker">每日更新</span><h2>🆕 最新App测评</h2></div></div>
    <div class="grid-2">{latest_html}</div>
  </div>
</section>

{newsletter_html()}
"""
    write_page(SITE / "index.html", layout(
        SITE_CFG["tagline"], SITE_CFG["description"], body, active="/", canonical="/"))


def build_posts():
    arts = sort_articles(ARTICLES)
    for a in arts:
        c = cat_of(a)
        content_html = render_markdown(a.get("content", ""))
        toc = build_toc(a.get("content", ""))
        # 相关文章：同分类优先，取 3 篇
        related = [x for x in arts if x["slug"] != a["slug"] and x.get("category") == a.get("category")]
        related += [x for x in arts if x["slug"] != a["slug"] and x not in related]
        related_html = "".join(article_card(x, compact=True) for x in related[:3])
        tags = "".join(f'<span class="tag">#{esc(t)}</span>' for t in a.get("tags", []))
        jsonld = f'''<script type="application/ld+json">
{{"@context":"https://schema.org","@type":"Article","headline":"{esc(a.get('title'))}",
"datePublished":"{esc(a.get('date'))}","dateModified":"{esc(a.get('updated', a.get('date')))}",
"author":{{"@type":"Organization","name":"{esc(SITE_CFG.get('author',''))}"}}}}
</script>'''
        body = f"""
<article class="post-page">
  <div class="post-header" style="--cat-color:{esc(c['color'])}">
    <div class="container">
      <div class="breadcrumb"><a href="/">首页</a> / <a href="/tools/">赚钱App</a> / <a href="/tools/{esc(c['slug'])}/">{esc(c['name'])}</a></div>
      <div class="post-header-top"><span class="cat-pill big">{esc(c['icon'])} {esc(c['name'])}</span><span class="post-date">{fmt_date(a.get('date'))} · ⏱ {esc(a.get('read_time',5))} 分钟阅读</span></div>
      <h1>{esc(a.get('title'))}</h1>
      <p class="post-lead">{esc(a.get('excerpt'))}</p>
    </div>
  </div>
  <div class="container post-layout">
    <div class="post-main">
      <div class="post-content">{content_html}</div>
      <div class="post-tags">{tags}</div>
      <div class="post-share"><span>觉得有用？分享给需要的朋友</span>
        <a href="#" onclick="return shareNow(event)" title="复制链接">🔗 复制链接</a>
      </div>
      <div class="post-author">
        <div class="author-avatar">✍️</div>
        <div><b>{esc(a.get('author', SITE_CFG.get('author','')))}</b><p>专注手机赚钱App测评，只推能提现的软件。</p></div>
      </div>
    </div>
    <aside class="post-side">
      {toc}
      <div class="side-aff">
        <div class="side-aff-title">🎯 文中提到的App</div>
        {''.join(aff_card(AFF_MAP[x]) for x in a.get('affiliate_ids', []) if x in AFF_MAP)}
      </div>
    </aside>
  </div>
</article>
<section class="section"><div class="container">
  <div class="section-head"><div><span class="kicker">继续阅读</span><h2>📚 你可能还想看</h2></div></div>
  <div class="grid-3">{related_html}</div>
</div></section>
{newsletter_html()}
{jsonld}
"""
        write_page(SITE / "posts" / a["slug"] / "index.html", layout(
            a["title"], a["excerpt"], body, canonical=url_of(a),
            og_emoji=a.get("emoji", "📱")))


def app_cat_count(slug):
    return sum(1 for a in AFFILIATES if a.get("category") == slug)


def app_cat_nav(active_slug=""):
    """统一分类导航条：全部 + 各分类（有 App 或有文章的都显示）。"""
    chips = [f'<a class="acn-chip{" on" if active_slug == "" else ""}" href="/tools/">📱 全部 <b>{len(AFFILIATES)}</b></a>']
    for c in CATEGORIES:
        n = app_cat_count(c["slug"])
        m = sum(1 for x in ARTICLES if x.get("category") == c["slug"])
        if n == 0 and m == 0:
            continue
        chips.append(
            f'<a class="acn-chip{" on" if active_slug == c["slug"] else ""}" '
            f'href="/tools/{esc(c["slug"])}/" style="--cat-color:{esc(c["color"])}">'
            f'{esc(c["icon"])} {esc(c["name"])} <b>{n}</b></a>'
        )
    return '<nav class="app-cat-nav">' + "".join(chips) + "</nav>"


def tool_card_html(a, arts):
    c = cat_of({"category": a.get("category")})
    pros = "".join(f"<li>{esc(p)}</li>" for p in a.get("pros", []))
    used = sum(1 for art in arts if a["id"] in art.get("affiliate_ids", []))
    wd = a.get("withdraw", {})
    pr = a.get("price", {})
    dims = (
        f'<div class="rank-tags tool-dims">'
        f'<span class="dim dim-wd">{esc(WD_LABEL.get(wd.get("label"), wd.get("label", "")))}</span>'
        f'<span class="dim dim-price">{esc(PRICE_LABEL.get(pr.get("label"), pr.get("label", "")))}</span>'
        f'</div>'
    )
    return f"""
<div class="tool-card filter-item" data-name="{esc(a.get('name',''))}" data-cat="{esc(c['name'])}"
     data-wd="{esc(wd.get('days',1))}" data-price="{esc(pr.get('level',2))}"
     data-rating="{esc(a.get('rating',0))}" data-score="{esc(a.get('score',0))}"
     data-aud="{esc(','.join(a.get('audience', [])))}"
     style="--aff-color:{esc(a.get('color','#4f46e5'))}">
  <div class="tool-top"><div class="tool-icon">{esc(a.get('emoji','💡'))}</div>
    <div><div class="tool-name">{esc(a.get('name'))}</div><div class="tool-type">{esc(c['icon'])} {esc(c['name'])} · {esc(a.get('type',''))}</div></div>
    <div class="tool-rating">{fmt_stars(a.get('rating'))}<small>{esc(a.get('rating'))}</small></div></div>
  <div class="tool-bonus">🎁 {esc(a.get('commission',''))}</div>
  <ul class="tool-pros">{pros}</ul>
  {dims}
  <div class="tool-foot"><span class="mini-tag">{esc(a.get('tag',''))}</span><span>{used} 篇测评提及</span>
    <a href="/posts/app-{esc(a['id'])}/">查看详情 →</a></div>
</div>"""


def build_tools():
    """赚钱App 主清单页：分类导航 + 全部 App。"""
    arts = sort_articles(ARTICLES)
    ranked = sorted(AFFILIATES, key=lambda a: (a.get("stopped", False), -a.get("score", 0)))
    items = "".join(tool_card_html(a, arts) for a in ranked)
    body = f"""
<section class="page-hero"><div class="container"><span class="kicker">亲测 · 精选 · 全免费</span><h1>📱 赚钱App</h1><p>{len(AFFILIATES)} 款亲测手机赚钱App，标注注册福利、提现门槛与适用场景。按下方分类快速找到你要的类型，通过联盟链接下载不增加你的成本。</p></div></section>
<section class="section"><div class="container">
  {app_cat_nav("")}
  <div class="tool-grid">{items}</div>
  <p class="aff-disclosure">联盟披露：部分链接为联盟链接，我们可能获得佣金。我们只推荐自己认可、亲测提现的App，佣金不影响排名与结论。</p>
</div></section>
"""
    write_page(SITE / "tools" / "index.html", layout(
        "赚钱App", "亲测靠谱的手机赚钱App大全，按分类找任务、问卷、看视频、游戏赚钱软件",
        body, active="/tools/", canonical="/tools/"))


def app_filter_bar(total):
    """分类页筛选栏：提现速度 / 单价 / 排序 / 搜索，复用排行榜通用 JS。"""
    return f"""
  <div data-filter-scope>
  <div class="rank-filters cat-filters">
    <div class="filter-group">
      <span class="filter-label">⚡ 提现速度</span>
      <div class="filter-chips" data-filter="wd">
        <button class="fchip active" data-val="all">全部</button>
        <button class="fchip" data-val="0.5">秒到</button>
        <button class="fchip" data-val="1">当天</button>
        <button class="fchip" data-val="3">1-3天</button>
      </div>
    </div>
    <div class="filter-group">
      <span class="filter-label">💰 单价</span>
      <div class="filter-chips" data-filter="price">
        <button class="fchip active" data-val="all">全部</button>
        <button class="fchip" data-val="3">高</button>
        <button class="fchip" data-val="2">中</button>
        <button class="fchip" data-val="1">低</button>
      </div>
    </div>
    <div class="filter-group">
      <span class="filter-label">🔄 排序</span>
      <div class="filter-chips" data-filter="sort">
        <button class="fchip active" data-val="score">综合</button>
        <button class="fchip" data-val="wd">提现最快</button>
        <button class="fchip" data-val="price">单价最高</button>
        <button class="fchip" data-val="rating">评分最高</button>
      </div>
    </div>
    <div class="filter-group filter-search">
      <span class="filter-label">🔍 找App</span>
      <input class="rank-search" type="text" data-filter-search placeholder="输入App名称…">
    </div>
  </div>
  <div class="rank-result-bar"><b data-filter-count>{total}</b> 款App符合条件<span> · <a href="#" data-filter-reset>重置筛选</a></span></div>
  <div class="tool-grid filter-list">{{ITEMS}}</div>
  <div class="empty" data-filter-empty hidden>没有符合条件的App，换个筛选试试 🙌</div>
  </div>"""


def build_app_categories():
    """统一分类页：/tools/<slug>/ 同时展示该类 App（可筛选）+ 该类文章。"""
    arts = sort_articles(ARTICLES)
    for c in CATEGORIES:
        matches = [a for a in AFFILIATES if a.get("category") == c["slug"]]
        cat_arts = [x for x in arts if x.get("category") == c["slug"]]
        if not matches and not cat_arts:
            continue
        matches.sort(key=lambda a: (a.get("stopped", False), -a.get("score", 0)))

        # App 区（带筛选）
        if matches:
            cards = "".join(tool_card_html(a, arts) for a in matches)
            app_section = app_filter_bar(len(matches)).replace("{ITEMS}", cards)
            app_meta = f'共 {len(matches)} 款App'
        else:
            app_section = '<p class="empty">该分类暂无收录的App，先看下面的测评文章。</p>'
            app_meta = '暂无App'

        # 文章区（并入原文章分类）
        if cat_arts:
            post_grid = "".join(article_card(a) for a in cat_arts)
            post_section = f"""
<section class="section section-alt"><div class="container">
  <div class="section-head"><div><span class="kicker">深度测评</span><h2>📚 {esc(c['name'])}相关攻略</h2></div></div>
  <div class="grid-3">{post_grid}</div>
</div></section>"""
        else:
            post_section = ""

        body = f"""
<section class="page-hero" style="--cat-color:{esc(c['color'])}"><div class="container">
  <div class="breadcrumb"><a href="/">首页</a> / <a href="/tools/">赚钱App</a> / {esc(c['name'])}</div>
  <span class="cat-pill big">{esc(c['icon'])} {esc(c['name'])}</span>
  <h1>{esc(c['icon'])} {esc(c['name'])}</h1><p>{esc(c['description'])}</p>
  <div class="page-hero-meta">{app_meta} · {len(cat_arts)} 篇测评</div>
</div></section>
<section class="section"><div class="container">
  {app_cat_nav(c['slug'])}
  {app_section}
  <p class="aff-disclosure">联盟披露：部分链接为联盟链接，我们可能获得佣金，不影响你的注册与使用。</p>
</div></section>
{post_section}
"""
        write_page(SITE / "tools" / c["slug"] / "index.html", layout(
            c["name"], c["description"], body,
            active="/tools/", canonical=f"/tools/{c['slug']}/"))


PLATFORM_INFO = {
    "android": {"icon": "🤖", "name": "安卓", "desc": "安卓手机可安装的赚钱App，数量最多、选择最广。", "color": "#16a34a"},
    "ios": {"icon": "🍎", "name": "苹果 iOS", "desc": "iPhone / iPad 专属的试玩与任务App，单价普遍更高。", "color": "#e11d48"},
    "both": {"icon": "🔄", "name": "双端通用", "desc": "安卓和苹果都能用，主流大厂出品，提现最稳。", "color": "#4f46e5"},
}
WD_LABEL = {"秒到": "⚡ 秒到", "当天": "✅ 当天", "1-3天": "🕐 1-3天"}
PRICE_LABEL = {"高": "💰 单价高", "中": "💵 单价中", "低": "🪙 单价低"}


def _rank_item(a, rank):
    c = cat_of({"category": a.get("category")})
    plat = PLATFORM_INFO.get(a.get("platform"), PLATFORM_INFO["android"])
    aud = "/".join(a.get("audience", []))
    wd = a.get("withdraw", {})
    pr = a.get("price", {})
    top_cls = " rank-top" if rank <= 3 else ""
    stopped = '<span class="rank-dead">已停运</span>' if a.get("stopped") else ""
    return f"""
<div class="rank-item filter-item{top_cls}" data-name="{esc(a.get('name',''))}" data-cat="{esc(c['name'])}"
     data-wd="{esc(wd.get('days',1))}" data-price="{esc(pr.get('level',2))}"
     data-rating="{esc(a.get('rating',0))}" data-score="{esc(a.get('score',0))}"
     data-aud="{esc(','.join(a.get('audience', [])))}" data-plat="{esc(a.get('platform',''))}">
  <div class="rank-no">{rank}</div>
  <div class="rank-icon" style="--aff-color:{esc(a.get('color','#4f46e5'))}">{esc(a.get('emoji','💡'))}</div>
  <div class="rank-main">
    <div class="rank-title">{esc(a.get('name'))} <span class="mini-tag">{esc(a.get('tag',''))}</span>{stopped}</div>
    <div class="rank-sub">{esc(c['icon'])} {esc(c['name'])} · {esc(a.get('type',''))} · ⭐ {esc(a.get('rating'))}</div>
    <div class="rank-tags">
      <span class="dim dim-wd">{esc(WD_LABEL.get(wd.get('label'), wd.get('label','')))}</span>
      <span class="dim dim-price">{esc(PRICE_LABEL.get(pr.get('label'), pr.get('label','')))}</span>
      <span class="dim dim-aud">👥 {esc(aud)}</span>
      <span class="dim dim-plat">{esc(plat['icon'])} {esc(plat['name'])}</span>
    </div>
  </div>
  <div class="rank-cta"><a class="btn btn-sm btn-primary" href="{esc(a.get('url'))}" target="_blank" rel="sponsored noopener">去试试 →</a></div>
</div>"""


def build_ranking():
    """可筛选排行榜专题页：按提现速度 / 单价 / 适合人群筛选 + 多维排序。"""
    ranked = sorted(AFFILIATES, key=lambda a: (a.get("stopped", False), -a.get("score", 0)))
    items = "".join(_rank_item(a, i + 1) for i, a in enumerate(ranked))
    # 内嵌精简数据供前端排序重排（用 data 属性即可，这里给出数量提示）
    total = len(ranked)
    body = f"""
<section class="page-hero rank-hero"><div class="container">
  <span class="kicker">按提现速度 · 单价 · 人群筛选</span>
  <h1>🏆 赚钱App排行榜</h1>
  <p>{total} 款亲测App一本账：想提现快的、单价高的、适合自己身份的，一筛就知道。综合分 = 评分 + 单价 + 提现速度。</p>
</div></section>
<section class="section"><div class="container">
  <div data-filter-scope>
  <div class="rank-filters">
    <div class="filter-group">
      <span class="filter-label">⚡ 提现速度</span>
      <div class="filter-chips" data-filter="wd">
        <button class="fchip active" data-val="all">全部</button>
        <button class="fchip" data-val="0.5">秒到</button>
        <button class="fchip" data-val="1">当天</button>
        <button class="fchip" data-val="3">1-3天</button>
      </div>
    </div>
    <div class="filter-group">
      <span class="filter-label">💰 单价</span>
      <div class="filter-chips" data-filter="price">
        <button class="fchip active" data-val="all">全部</button>
        <button class="fchip" data-val="3">高</button>
        <button class="fchip" data-val="2">中</button>
        <button class="fchip" data-val="1">低</button>
      </div>
    </div>
    <div class="filter-group">
      <span class="filter-label">👥 适合人群</span>
      <div class="filter-chips" data-filter="aud">
        <button class="fchip active" data-val="all">全部</button>
        <button class="fchip" data-val="所有人">所有人</button>
        <button class="fchip" data-val="新手">新手</button>
        <button class="fchip" data-val="学生">学生</button>
        <button class="fchip" data-val="宝妈">宝妈</button>
        <button class="fchip" data-val="上班族">上班族</button>
      </div>
    </div>
    <div class="filter-group">
      <span class="filter-label">🔄 排序</span>
      <div class="filter-chips" data-filter="sort">
        <button class="fchip active" data-val="score">综合</button>
        <button class="fchip" data-val="wd">提现最快</button>
        <button class="fchip" data-val="price">单价最高</button>
        <button class="fchip" data-val="rating">评分最高</button>
      </div>
    </div>
    <div class="filter-group filter-search">
      <span class="filter-label">🔍 找App</span>
      <input class="rank-search" type="text" data-filter-search placeholder="输入名称，如：赏帮赚、钱咖…">
    </div>
  </div>
  <div class="rank-result-bar"><b data-filter-count>{total}</b> 款App符合条件<span> · <a href="#" data-filter-reset>重置筛选</a></span></div>
  <div class="rank-list filter-list">{items}</div>
  <div class="empty" data-filter-empty hidden>没有符合条件的App，换个筛选试试 🙌</div>
  <p class="aff-disclosure">联盟披露：部分链接为联盟链接，我们可能获得佣金，不影响你的注册与使用。综合分为本站测评参考，非收益承诺；收益因人而异，警惕需先交费的平台。</p>
  </div>
</div></section>
"""
    write_page(SITE / "ranking" / "index.html", layout(
        "赚钱App排行榜", "按提现速度、单价、适合人群筛选66款赚钱App，找到最适合你的那一款",
        body, active="/ranking/", canonical="/ranking/", og_emoji="🏆"))


def build_about():
    features = [
        ("🎯", "只推能提现", "每款App都讲清提现门槛与到账速度，拒绝提不了现的坑。"),
        ("🔍", "真实测评", "亲测每款赚钱App，坦诚标注收益水平与套路，不夸大、不画饼。"),
        ("🔄", "每日更新", "紧跟新App红利与平台变化，第一时间拆解赚钱机会。"),
        ("🤝", "联盟透明", "推荐链接可能带来佣金，但绝不因此影响结论，收录标准公开。"),
    ]
    feat_html = "".join(
        f'<div class="feature"><div class="feature-icon">{i}</div><h3>{t}</h3><p>{d}</p></div>'
        for i, t, d in features)
    body = f"""
<section class="page-hero"><div class="container"><span class="kicker">关于我们</span><h1>👋 关于 {esc(SITE_CFG['name'])}</h1><p>{esc(SITE_CFG.get('description',''))}</p></div></section>
<section class="section"><div class="container"><div class="grid-4">{feat_html}</div></div></section>
<section class="section section-alt"><div class="container prose" id="affiliate">
  <h2>🤝 联盟披露 (Affiliate Disclosure)</h2>
  <p>{esc(SITE_CFG['name'])} 的部分链接为联盟链接（Affiliate Link）。如果你通过这些链接注册或购买，我们可能获得一定比例的佣金，但<strong>你支付的价格不会因此增加</strong>。</p>
  <p>我们只推荐自己亲测并认可的手机赚钱App，佣金绝不作为收录与排名的依据。你的信任比佣金更重要。</p>
  <h2 id="disclaimer">⚠️ 内容免责声明</h2>
  <p>本站内容仅为信息参考与经验分享，不构成任何投资或法律建议。手机赚钱App收益因人而异，文中提到的收入数据为个案，不构成收益承诺。请遵守所在地区的法律法规，理性判断、量力而行，警惕需要交费或涉嫌传销的平台。</p>
  <h2 id="contact">📮 联系我们</h2>
  <p>商务合作、内容纠错、投稿建议，欢迎发邮件至：<a href="mailto:{esc(SITE_CFG.get('email',''))}">{esc(SITE_CFG.get('email',''))}</a></p>
</div></section>
"""
    write_page(SITE / "about" / "index.html", layout(
        "关于我们", SITE_CFG.get("description", ""), body, active="/about/", canonical="/about/"))


def build_search():
    body = f"""
<section class="page-hero"><div class="container"><span class="kicker">站内搜索</span><h1>🔍 找点什么</h1><p>搜索App名称、标签与内容，快速找到你要的赚钱测评。</p></div></section>
<section class="section"><div class="container">
  <div class="search-box"><input id="search-input" type="text" placeholder="输入关键词，如：抖音、提现、闲鱼…" autofocus><span id="search-count"></span></div>
  <div id="search-results" class="grid-2"></div>
  <div class="quick-tags"><b>热门搜索：</b>{''.join(f'<button class="quick-tag" data-q="{esc(t)}">{esc(t)}</button>' for t in ['抖音','提现','闲鱼','小说','问卷','看视频'])}</div>
</div></section>
"""
    write_page(SITE / "search" / "index.html", layout(
        "站内搜索", "搜索全站手机赚钱App测评", body, canonical="/search/"))


def build_404():
    body = """
<section class="notfound"><div class="container">
  <div class="nf-code">404</div><h1>这个页面跑路了 💨</h1>
  <p>你要找的内容可能已搬家或从未存在。不如回到首页继续挖宝。</p>
  <a class="btn btn-primary btn-lg" href="/">返回首页 →</a>
</div></section>
"""
    write_page(SITE / "404.html", layout("页面未找到", "404", body, canonical="/404"))


def build_search_index():
    arts = sort_articles(ARTICLES)
    idx = []
    for a in arts:
        c = cat_of(a)
        idx.append({
            "title": a.get("title", ""),
            "excerpt": a.get("excerpt", ""),
            "url": url_of(a),
            "category": c["name"],
            "emoji": a.get("emoji", "📄"),
            "color": a.get("color", c["color"]),
            "tags": a.get("tags", []),
            "text": (a.get("title", "") + " " + a.get("excerpt", "") + " "
                     + " ".join(a.get("tags", [])) + " " + a.get("content", "")).lower(),
        })
    write_text(SITE / "search-index.json", json.dumps(idx, ensure_ascii=False))


def build_sitemap():
    domain = SITE_CFG.get("domain", "").rstrip("/")
    today = datetime.now().strftime("%Y-%m-%d")
    urls = [("/", today, "1.0"),
            ("/ranking/", today, "0.9"), ("/tools/", today, "0.85"),
            ("/about/", today, "0.5"), ("/search/", today, "0.3")]
    for c in CATEGORIES:
        n_app = app_cat_count(c["slug"])
        n_art = sum(1 for x in ARTICLES if x.get("category") == c["slug"])
        if n_app > 0 or n_art > 0:
            urls.append((f"/tools/{c['slug']}/", today, "0.75"))
    for a in sort_articles(ARTICLES):
        urls.append((url_of(a), a.get("updated", a.get("date", today)), "0.9"))
    entries = "".join(
        f"<url><loc>{esc(domain + loc)}</loc><lastmod>{lm}</lastmod><changefreq>weekly</changefreq><priority>{p}</priority></url>"
        for loc, lm, p in urls)
    xml = f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{entries}</urlset>'
    write_text(SITE / "sitemap.xml", xml)


def build_robots():
    domain = SITE_CFG.get("domain", "").rstrip("/")
    write_text(SITE / "robots.txt", f"""User-agent: *
Allow: /

Sitemap: {domain}/sitemap.xml
""")


# ----------------------------------------------------------------------------
# 写文件
# ----------------------------------------------------------------------------
def write_page(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_text(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def clean_output():
    """清理动态生成的目录，避免删除遗留页面。assets 保留。"""
    # categories / platforms 为历史遗留目录，仅清理不再生成
    for name in ["posts", "categories", "tools", "ranking", "platforms", "about", "search"]:
        p = SITE / name
        if p.exists():
            shutil.rmtree(p)


def copy_static_files():
    """把 static/ 下的文件（如百度/Google 站长验证 HTML）复制到站点根目录。
    这些文件必须长期存在于域名根目录，且不能被 clean_output 清理，故源码持久化于此。"""
    if not STATIC.exists():
        return
    n = 0
    for src in STATIC.iterdir():
        if src.is_file():
            shutil.copy2(src, SITE / src.name)
            n += 1
    if n:
        print(f"   📄 已复制 {n} 个静态验证文件到站点根目录")


def main():
    clean_output()
    copy_static_files()
    build_home()
    build_posts()
    build_tools()
    build_app_categories()
    build_ranking()
    build_about()
    build_search()
    build_404()
    build_search_index()
    build_sitemap()
    build_robots()
    # 统计
    pages = list(SITE.rglob("*.html"))
    print(f"✅ 构建完成：{len(pages)} 个 HTML 页面，{len(ARTICLES)} 篇文章，{len(AFFILIATES)} 个联盟项目")
    print(f"   输出目录：{SITE}")


if __name__ == "__main__":
    main()
