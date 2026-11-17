#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信草稿箱同步脚本 —— 赚钱App大全
=====================================
把站点文章转成微信内联样式 HTML，上传图片到微信素材库，写入公众号草稿箱。
最后一步「群发」保留在公众号后台人工完成（个人订阅号也符合微信合规要求）。

能力边界（2026 现行规则）：
  - 个人未认证订阅号：可获取 token、上传素材、草稿箱增删查；发布/群发接口已回收
  - 因此本脚本只做到「进草稿箱」，不会也无法自动群发

用法：
  # 1) 先配置 config/wechat.json（或从环境变量读取，见下方 ENV）
  # 2) 预览某篇文章生成的 HTML（不调接口，安全）
  python scripts/wechat_draft.py --dry-run --slug app-zhongrenbang

  # 3) 同步最新 N 篇未推送文章到草稿箱
  python scripts/wechat_draft.py --latest 1

  # 4) 同步指定文章
  python scripts/wechat_draft.py --slug app-zhongrenbang

  # 5) 查看已同步状态
  python scripts/wechat_draft.py --status

  # 6) 重置某篇的已同步标记（重新生成草稿用）
  python scripts/wechat_draft.py --reset app-zhongrenbang

凭证配置（二选一，环境变量优先）：
  ENV: WECHAT_APPID / WECHAT_APPSECRET / WECHAT_AUTHOR / WECHAT_SOURCE_URL
  文件: config/wechat.json
  {
    "appid": "wx...",
    "appsecret": "...",
    "author": "赚钱App大全编辑部",
    "source_url": "https://money.72tool.com",
    "ip_whitelist_note": "家宽IP变动需到公众平台更新IP白名单"
  }

依赖：requests、Pillow（pip install requests pillow）
"""
import json
import html
import re
import sys
import time
import argparse
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta

try:
    import requests
except ImportError:
    sys.exit("缺少 requests，请先运行：pip install requests pillow")

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SITE = ROOT / "site"
CONFIG_PATH = ROOT / "config" / "wechat.json"
STATE_PATH = DATA / "wechat_state.json"          # 记录已同步的 slug，防重复
TOKEN_CACHE = ROOT / ".workbuddy" / ".wechat_token.json"  # token 缓存（gitignore）

WX_API = "https://api.weixin.qq.com/cgi-bin"

# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------
def load_json(path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


ARTICLES = load_json(DATA / "articles.json", [])
AFFILIATES = load_json(DATA / "affiliates.json", [])
CATEGORIES = load_json(DATA / "categories.json", [])
MEDIA = load_json(DATA / "app_media.json", {"trusted_screenshots": [], "info": {}})
SITE_CFG = load_json(DATA / "site.json", {})

AFF_MAP = {a["id"]: a for a in AFFILIATES}
CAT_MAP = {c["slug"]: c for c in CATEGORIES}
APP_INFO = MEDIA.get("info", {})
TRUSTED = set(MEDIA.get("trusted_screenshots", []))


def load_config():
    """环境变量优先，其次 config/wechat.json。"""
    cfg = load_json(CONFIG_PATH, {}) or {}
    env_map = {
        "appid": "WECHAT_APPID",
        "appsecret": "WECHAT_APPSECRET",
        "author": "WECHAT_AUTHOR",
        "source_url": "WECHAT_SOURCE_URL",
    }
    for key, env in env_map.items():
        if os.environ.get(env):
            cfg[key] = os.environ[env]
    cfg.setdefault("author", SITE_CFG.get("author", "赚钱App大全编辑部"))
    cfg.setdefault("source_url", SITE_CFG.get("domain", "").rstrip("/"))
    return cfg


# ---------------------------------------------------------------------------
# 微信 API 封装
# ---------------------------------------------------------------------------
class WeChat:
    def __init__(self, appid, appsecret):
        self.appid = appid
        self.appsecret = appsecret
        self.token = None

    def _check(self, data, ctx):
        if not isinstance(data, dict):
            raise RuntimeError(f"{ctx}: 接口返回非 JSON -> {str(data)[:200]}")
        code = data.get("errcode", 0)
        if code not in (0, None):
            msg = data.get("errmsg", "")
            hint = ""
            if code == 40164:
                hint = "\n  ⚠️ IP 不在白名单：请到 公众平台 → 设置与开发 → 基本配置 → IP白名单，把当前公网 IP 加进去。"
            elif code == 40001:
                hint = "\n  ⚠️ AppSecret 错误或 token 无效，请核对配置。"
            elif code == 48001:
                hint = "\n  ⚠️ 接口未授权：该能力需微信认证，个人订阅号无法使用。"
            raise RuntimeError(f"{ctx}: errcode={code} errmsg={msg}{hint}")
        return data

    def get_token(self, force=False):
        """获取 access_token，带本地缓存（2 小时有效，提前 5 分钟刷新）。"""
        if not force and self.token:
            return self.token
        cache = load_json(TOKEN_CACHE, {}) or {}
        if (not force and cache.get("appid") == self.appid
                and cache.get("expire_at", 0) > time.time() + 300):
            self.token = cache["access_token"]
            return self.token
        r = requests.get(f"{WX_API}/token", params={
            "grant_type": "client_credential",
            "appid": self.appid,
            "secret": self.appsecret,
        }, timeout=20)
        data = self._check(r.json(), "获取 access_token")
        self.token = data["access_token"]
        TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
        with open(TOKEN_CACHE, "w", encoding="utf-8") as f:
            json.dump({
                "appid": self.appid,
                "access_token": self.token,
                "expire_at": time.time() + data.get("expires_in", 7200),
            }, f)
        return self.token

    def upload_image(self, file_path):
        """上传正文图片到微信，返回微信内部 URL（uploadimg，不占素材库配额）。"""
        token = self.get_token()
        # 微信正文图仅支持 jpg/png，webp 需转换
        path, need_cleanup = ensure_jpg(Path(file_path))
        try:
            with open(path, "rb") as f:
                r = requests.post(
                    f"{WX_API}/media/uploadimg",
                    params={"access_token": token},
                    files={"media": (path.name, f, "image/jpeg")},
                    timeout=60,
                )
            data = self._check(r.json(), f"上传正文图 {Path(file_path).name}")
            return data["url"]
        finally:
            if need_cleanup:
                try:
                    path.unlink()
                except Exception:
                    pass

    def add_material(self, file_path):
        """上传永久图片素材，返回 media_id（用作草稿封面 thumb_media_id）。"""
        token = self.get_token()
        path, need_cleanup = ensure_jpg(Path(file_path))
        try:
            with open(path, "rb") as f:
                r = requests.post(
                    f"{WX_API}/material/add_material",
                    params={"access_token": token, "type": "image"},
                    files={"media": (path.name, f, "image/jpeg")},
                    timeout=60,
                )
            data = self._check(r.json(), f"上传封面素材 {Path(file_path).name}")
            return data["media_id"]
        finally:
            if need_cleanup:
                try:
                    path.unlink()
                except Exception:
                    pass

    def add_draft(self, articles):
        """新增图文草稿。articles 为微信图文项列表。"""
        token = self.get_token()
        r = requests.post(
            f"{WX_API}/draft/add",
            params={"access_token": token},
            data=json.dumps({"articles": articles}, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            timeout=60,
        )
        data = self._check(r.json(), "新增草稿")
        return data.get("media_id", "")


def ensure_jpg(path: Path):
    """微信只认 jpg/png；webp 转成 jpg。返回 (实际路径, 是否为临时文件)。"""
    if path.suffix.lower() in (".jpg", ".jpeg", ".png"):
        return path, False
    try:
        from PIL import Image
        img = Image.open(path).convert("RGB")
        tmp = path.with_suffix(".wx_tmp.jpg")
        img.save(tmp, "JPEG", quality=85, optimize=True)
        return tmp, True
    except Exception as e:
        raise RuntimeError(f"图片转换失败 {path}: {e}")


# ---------------------------------------------------------------------------
# 状态管理（去重）
# ---------------------------------------------------------------------------
def load_state():
    return load_json(STATE_PATH, {"synced": {}}) or {"synced": {}}


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 内联样式渲染（微信会剥离 class 和 <style>，全部写死在 style 属性里）
# ---------------------------------------------------------------------------
def esc(s):
    return html.escape(str(s), quote=True)


C_BG = "#ffffff"
C_TEXT = "#333333"
C_SUB = "#888888"
C_LINE = "#eeeeee"
C_ACCENT = "#2563eb"


def inline_md(text):
    """行内 Markdown：加粗、行内码、链接（微信正文外链会被限制，链接转脚注）。"""
    t = html.escape(text, quote=False)
    t = re.sub(r"`([^`]+)`",
               r'<code style="background:#f5f5f5;padding:1px 5px;border-radius:3px;font-size:14px;color:#c7254e;">\1</code>', t)
    t = re.sub(r"\*\*([^*]+)\*\*", r'<strong style="color:#111;font-weight:700;">\1</strong>', t)
    # 微信正文不支持普通外链跳转，保留文字但去掉 href（文末统一放"阅读原文"）
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'\1', t)
    return t


def render_app_info_wx(aid):
    a = AFF_MAP.get(aid.strip())
    info = APP_INFO.get(aid.strip(), {})
    if not a:
        return ""
    rows = []
    if info.get("company"):
        rows.append(("运营主体", info["company"]))
    rows.append(("赚钱方式", info.get("gameplay", a.get("type", ""))))
    rows.append(("提现规则", info.get("withdraw", a.get("commission", ""))))
    rows_html = "".join(
        f'<div style="display:flex;padding:6px 0;font-size:14px;line-height:1.6;'
        f'border-bottom:1px solid {C_LINE};"><span style="flex:0 0 72px;color:{C_SUB};">{esc(k)}</span>'
        f'<span style="flex:1;color:{C_TEXT};">{esc(v)}</span></div>'
        for k, v in rows
    )
    return (
        f'<section style="margin:20px 0;border:1px solid {C_LINE};border-radius:10px;overflow:hidden;">'
        f'<div style="background:linear-gradient(135deg,#2563eb,#4f46e5);padding:14px 16px;color:#fff;">'
        f'<div style="font-size:18px;font-weight:700;">{esc(a.get("emoji","📱"))} {esc(a.get("name"))}</div>'
        f'<div style="font-size:12px;opacity:.85;margin-top:4px;">{esc(info.get("hook", a.get("tag","")))}</div>'
        f'</div>'
        f'<div style="padding:10px 16px;">{rows_html}'
        f'<div style="font-size:12px;color:{C_SUB};margin-top:10px;">📌 运营信息经公开资料核实，具体以 App 内为准</div>'
        f'</div></section>'
    )


def render_income_wx(aid):
    a = AFF_MAP.get(aid.strip())
    if not a:
        return ""
    pr = a.get("price", {})
    level = pr.get("level", 2)
    today = {1: "6.5", 2: "15.0", 3: "32.0"}.get(level, "15.0")
    month = {1: "约 120", 2: "约 320", 3: "约 680"}.get(level, "约 320")
    tasks = {1: "8", 2: "14", 3: "22"}.get(level, "14")
    return (
        f'<figure style="margin:20px 0;padding:16px;border:1px dashed #f59e0b;border-radius:10px;background:#fffbeb;">'
        f'<div style="font-size:14px;font-weight:700;color:#b45309;margin-bottom:10px;">💰 {esc(a.get("name"))} · 收益界面示意</div>'
        f'<div style="background:#fff;border-radius:8px;padding:14px;">'
        f'<div style="font-size:12px;color:{C_SUB};">累计收益（元）</div>'
        f'<div style="font-size:28px;font-weight:800;color:#dc2626;margin:4px 0;">{month}</div>'
        f'<div style="display:flex;gap:10px;margin-top:10px;">'
        f'<div style="flex:1;background:#f9fafb;border-radius:6px;padding:8px;text-align:center;">'
        f'<div style="font-size:12px;color:{C_SUB};">今日收益</div><div style="font-weight:700;">¥{today}</div></div>'
        f'<div style="flex:1;background:#f9fafb;border-radius:6px;padding:8px;text-align:center;">'
        f'<div style="font-size:12px;color:{C_SUB};">今日任务</div><div style="font-weight:700;">{tasks} 单</div></div>'
        f'</div></div>'
        f'<figcaption style="font-size:12px;color:{C_SUB};margin-top:10px;line-height:1.6;">'
        f'⚠️ 收益界面示意 · 数字按平台单价水平示例，非真实收款凭证，实际收益因人而异</figcaption>'
        f'</figure>'
    )


def render_gallery_wx(aid, wx):
    """真实截图画廊：本地图上传到微信，返回内部 URL。"""
    aid = aid.strip()
    a = AFF_MAP.get(aid)
    if not a:
        return ""
    folder = SITE / "assets" / "apps" / aid
    shots = [folder / f"web{i}.webp" for i in range(1, 4) if (folder / f"web{i}.webp").exists()]
    if not shots and aid in TRUSTED:
        shots = [folder / f"shot{i}.webp" for i in range(1, 4) if (folder / f"shot{i}.webp").exists()]
    if not shots:
        return ""
    imgs = ""
    for p in shots:
        try:
            url = wx.upload_image(p) if wx else f"/{p.relative_to(SITE).as_posix()}"
            imgs += (f'<img src="{esc(url)}" alt="{esc(a.get("name"))}界面截图" '
                     f'style="width:100%;display:block;border-radius:8px;margin:8px 0;">')
        except Exception as e:
            imgs += (f'<div style="padding:12px;background:#f5f5f5;border-radius:6px;color:{C_SUB};font-size:13px;">'
                     f'[截图上传失败: {esc(str(e)[:60])}]</div>')
    return (
        f'<section style="margin:20px 0;">'
        f'<h3 style="font-size:17px;font-weight:700;border-left:4px solid {C_ACCENT};padding-left:10px;margin:0 0 10px;">📱 {esc(a.get("name"))} 真实界面截图</h3>'
        f'<p style="font-size:13px;color:{C_SUB};line-height:1.6;">来自公开软件介绍页与测评文章，经人工核对，供你了解实际界面。</p>'
        f'{imgs}</section>'
    )


def render_affiliate_wx(aid):
    """合规版下载卡片：不放返利直链，引导去自有站点（微信打击外链返利/诱导分享）。"""
    a = AFF_MAP.get(aid.strip())
    if not a:
        return ""
    pros = "".join(
        f'<li style="margin:4px 0;font-size:14px;">✓ {esc(p)}</li>' for p in a.get("pros", [])[:4]
    )
    return (
        f'<section style="margin:20px 0;border:1px solid {C_LINE};border-radius:10px;padding:16px;background:#fafafa;">'
        f'<div style="font-size:16px;font-weight:700;">{esc(a.get("emoji","💡"))} {esc(a.get("name"))}</div>'
        f'<div style="font-size:13px;color:{C_SUB};margin:6px 0;">🎁 {esc(a.get("commission",""))}</div>'
        f'<ul style="margin:8px 0;padding-left:18px;">{pros}</ul>'
        f'<div style="font-size:13px;color:{C_ACCENT};margin-top:10px;">'
        f'👉 下载方式与最新提现攻略，请到本站查看完整测评</div>'
        f'</section>'
    )


AFF_RE = re.compile(r"^\[\[affiliate:([^\]]+)\]\]$")
INCOME_RE = re.compile(r"^\[\[income:([^\]]+)\]\]$")
APPINFO_RE = re.compile(r"^\[\[appinfo:([^\]]+)\]\]$")
GALLERY_RE = re.compile(r"^\[\[gallery:([^\]]+)\]\]$")


def render_markdown_wx(md, wx=None):
    """把文章 Markdown 渲染成微信内联样式 HTML。"""
    lines = md.split("\n")
    out = []
    i, n = 0, len(lines)
    while i < n:
        s = lines[i].strip()
        if not s:
            i += 1
            continue
        m = AFF_RE.match(s)
        if m:
            out.append(render_affiliate_wx(m.group(1))); i += 1; continue
        m = INCOME_RE.match(s)
        if m:
            out.append(render_income_wx(m.group(1))); i += 1; continue
        m = APPINFO_RE.match(s)
        if m:
            out.append(render_app_info_wx(m.group(1))); i += 1; continue
        m = GALLERY_RE.match(s)
        if m:
            out.append(render_gallery_wx(m.group(1), wx)); i += 1; continue
        if s.startswith("```"):
            i += 1; buf = []
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(html.escape(lines[i])); i += 1
            i += 1
            out.append(f'<pre style="background:#f6f8fa;padding:12px;border-radius:6px;overflow-x:auto;font-size:13px;">'
                       f'<code>{"<br>".join(buf)}</code></pre>')
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            lvl = len(m.group(1))
            size = {1: 22, 2: 19, 3: 17, 4: 16}.get(lvl, 15)
            out.append(f'<h{lvl} style="font-size:{size}px;font-weight:800;color:#111;margin:24px 0 12px;'
                       f'line-height:1.4;">{inline_md(m.group(2))}</h{lvl}>')
            i += 1; continue
        if s.startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip(">").strip()); i += 1
            out.append(f'<blockquote style="margin:16px 0;padding:12px 14px;background:#f3f4f6;'
                       f'border-left:4px solid {C_ACCENT};border-radius:4px;color:#555;font-size:15px;line-height:1.7;">'
                       f'{inline_md(" ".join(buf))}</blockquote>')
            continue
        if re.match(r"^[-*]\s+", s):
            buf = []
            while i < n and re.match(r"^[-*]\s+", lines[i].strip()):
                buf.append(f'<li style="margin:6px 0;font-size:15px;line-height:1.7;">'
                           f'{inline_md(re.sub(r"^[-*]\s+", "", lines[i].strip()))}</li>')
                i += 1
            out.append(f'<ul style="margin:12px 0;padding-left:22px;">{"".join(buf)}</ul>')
            continue
        if re.match(r"^\d+\.\s+", s):
            buf = []
            while i < n and re.match(r"^\d+\.\s+", lines[i].strip()):
                buf.append(f'<li style="margin:6px 0;font-size:15px;line-height:1.7;">'
                           f'{inline_md(re.sub(r"^\d+\.\s+", "", lines[i].strip()))}</li>')
                i += 1
            out.append(f'<ol style="margin:12px 0;padding-left:22px;">{"".join(buf)}</ol>')
            continue
        # 段落
        buf = [s]; i += 1
        while i < n:
            ns = lines[i].strip()
            if not ns:
                break
            if (ns.startswith("```") or ns.startswith(">") or AFF_RE.match(ns) or INCOME_RE.match(ns)
                    or APPINFO_RE.match(ns) or GALLERY_RE.match(ns)
                    or re.match(r"^#{1,6}\s", ns) or re.match(r"^[-*]\s+", ns) or re.match(r"^\d+\.\s+", ns)):
                break
            buf.append(ns); i += 1
        out.append(f'<p style="font-size:15px;line-height:1.9;color:{C_TEXT};margin:12px 0;">'
                   f'{inline_md(" ".join(buf))}</p>')
    return "\n".join(out)


def build_wx_article(post, wx=None, cfg=None):
    """组装一篇微信图文项（含封面、标题、作者、正文、原文链接）。"""
    cfg = cfg or {}
    body = render_markdown_wx(post.get("content", ""), wx)

    # 封面：优先用 App 截图，否则用站点 logo 占位（微信要求必须有 thumb_media_id）
    thumb = ""
    cover_candidates = []
    aid = post.get("app_id") or (post.get("affiliate_ids") or [None])[0]
    if aid:
        folder = SITE / "assets" / "apps" / aid
        for name in ("web1.webp", "shot1.webp", "icon.webp"):
            if (folder / name).exists():
                cover_candidates.append(folder / name)
    if cover_candidates and wx:
        try:
            thumb = wx.add_material(cover_candidates[0])
        except Exception as e:
            print(f"  ⚠️ 封面上传失败，尝试下一张：{e}")

    # 免责 + 原文引导（合规：不放返利直链，只引导到自有站点）
    source_url = cfg.get("source_url", "").rstrip("/")
    post_url = f"{source_url}/posts/{post['slug']}/" if source_url else ""
    tail = (
        '<section style="margin-top:28px;padding-top:16px;border-top:1px solid #eee;">'
        '<p style="font-size:12px;color:#999;line-height:1.7;">'
        '⚠️ 本文为信息整理与体验分享，不构成收益承诺。赚钱App收益因人而异，请理性参与、注意个人信息与资金安全。'
        '</p>'
    )
    if post_url:
        tail += (f'<p style="font-size:14px;color:#2563eb;">'
                 f'📖 完整测评、下载方式与提现攻略，点击文末「阅读原文」查看</p>')
    tail += '</section>'

    return {
        "title": post.get("title", "")[:64],
        "author": cfg.get("author", SITE_CFG.get("author", "赚钱App大全编辑部")),
        "digest": post.get("excerpt", "")[:120],
        "content": body + tail,
        "content_source_url": post_url,
        "thumb_media_id": thumb,
        "show_cover_pic": 0,
        "need_open_comment": 0,
        "only_fans_can_comment": 0,
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def sorted_posts():
    return sorted(ARTICLES, key=lambda a: a.get("date", ""), reverse=True)


def cmd_status():
    state = load_state()
    synced = state.get("synced", {})
    print(f"已同步文章：{len(synced)} 篇")
    if synced:
        print(f"{'slug':<28} {'同步时间':<22} 标题")
        for slug, meta in synced.items():
            print(f"{slug:<28} {meta.get('at',''):<22} {meta.get('title','')[:30]}")


def cmd_reset(slug):
    state = load_state()
    if slug in state.get("synced", {}):
        del state["synced"][slug]
        save_state(state)
        print(f"✅ 已清除 {slug} 的同步标记，下次可重新生成草稿")
    else:
        print(f"ℹ️ {slug} 未记录同步状态")


def cmd_sync(args, cfg):
    need_appid = not args.dry_run
    if need_appid and (not cfg.get("appid") or not cfg.get("appsecret")):
        sys.exit("缺少 AppID/AppSecret：请配置 config/wechat.json 或设置环境变量 WECHAT_APPID / WECHAT_APPSECRET")

    wx = None
    if need_appid:
        wx = WeChat(cfg["appid"], cfg["appsecret"])
        wx.get_token()
        print(f"✅ access_token 获取成功")

    posts = sorted_posts()
    if args.slug:
        targets = [p for p in posts if p["slug"] == args.slug]
        if not targets:
            sys.exit(f"找不到 slug：{args.slug}")
    elif args.latest:
        state = load_state()
        synced = state.get("synced", {})
        fresh = [p for p in posts if p["slug"] not in synced]
        targets = fresh[:args.latest]
        if not targets:
            print("ℹ️ 没有未同步的新文章")
            return
    else:
        sys.exit("请指定 --slug / --latest N / --status / --dry-run")

    state = load_state()
    for p in targets:
        slug = p["slug"]
        if not args.dry_run and not args.force and slug in state.get("synced", {}):
            print(f"⏭️ 跳过已同步：{slug}（用 --force 强制重新生成）")
            continue
        print(f"\n{'🔍 预览' if args.dry_run else '📤 同步'}: {p['title'][:40]}")
        if args.dry_run:
            art = build_wx_article(p, None, cfg)
            print(f"  标题: {art['title']}")
            print(f"  摘要: {art['digest'][:60]}...")
            print(f"  正文长度: {len(art['content'])} 字符")
            print(f"  原文链接: {art['content_source_url'] or '(未配置)'}")
            print(f"  封面 media_id: {art['thumb_media_id'] or '(dry-run 不上传)'}")
            preview = ROOT / "_wechat_preview.html"
            preview.write_text(
                '<!doctype html><meta charset="utf-8"><title>微信预览</title>'
                '<div style="max-width:420px;margin:auto;padding:16px;font-family:-apple-system,sans-serif;">'
                + art["content"] + '</div>', encoding="utf-8")
            print(f"  📄 预览已写入: {preview}")
        else:
            art = build_wx_article(p, wx, cfg)
            if not art["thumb_media_id"]:
                print(f"  ⚠️ 无封面素材，草稿可能创建失败，仍尝试...")
            media_id = wx.add_draft([art])
            state.setdefault("synced", {})[slug] = {
                "at": datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S"),
                "title": p.get("title", ""),
                "media_id": media_id,
            }
            save_state(state)
            print(f"  ✅ 草稿已创建 media_id={media_id[:20]}... 请到公众号后台群发")

    print(f"\n完成。当前已同步 {len(state.get('synced', {}))} 篇。")


def main():
    ap = argparse.ArgumentParser(description="微信草稿箱同步脚本")
    ap.add_argument("--latest", type=int, metavar="N", help="同步最近 N 篇未推送文章")
    ap.add_argument("--slug", help="同步指定 slug")
    ap.add_argument("--dry-run", action="store_true", help="只生成预览 HTML，不调用微信接口")
    ap.add_argument("--status", action="store_true", help="查看已同步状态")
    ap.add_argument("--reset", metavar="SLUG", help="清除某篇的同步标记")
    ap.add_argument("--force", action="store_true", help="强制重新生成已同步的文章")
    args = ap.parse_args()

    if args.status:
        cmd_status(); return
    if args.reset:
        cmd_reset(args.reset); return
    if not (args.latest or args.slug or args.dry_run):
        ap.print_help(); return

    cfg = load_config()
    cmd_sync(args, cfg)


if __name__ == "__main__":
    main()
