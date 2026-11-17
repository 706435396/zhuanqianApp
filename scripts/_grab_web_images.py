# -*- coding: utf-8 -*-
"""
精准抓图 v2：读 data/image_sources.json (id -> 页面URL)
策略：优先定位页面中「应用截图/软件截图/APP截图/游戏截图」关键词后的图片区块，
      只取该区块内的图；若无该区块，退回取正文区图片。下载->筛选竖版->压缩webp。
"""
import json, re, html, subprocess, hashlib, io
from pathlib import Path
from urllib.parse import urljoin
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
ASSETS = SITE / "assets" / "apps"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
UA_M = "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 Version/15.0 Mobile Safari/604.1"

sources = json.load(open(ROOT / "data" / "image_sources.json", encoding="utf-8"))
SHOT_KW = ["应用截图", "软件截图", "APP截图", "App截图", "游戏截图", "界面截图", "截图Screenshot", "Screenshot"]


def curl(url, binary=False, ua=UA, timeout=18):
    cmd = ["curl", "-s", "-L", "--compressed", "--max-time", str(timeout), "-A", ua]
    if binary:
        return subprocess.run(cmd + [url], capture_output=True).stdout
    return subprocess.run(cmd + [url], capture_output=True).stdout.decode("utf-8", "ignore")


def norm_url(f, base):
    f = html.unescape(f.strip())
    if f.startswith("//"):
        return "https:" + f
    if f.startswith("/"):
        return urljoin(base, f)
    return f if f.startswith("http") else ""


def extract_region_imgs(ph, base):
    """定位截图关键词后的图片区块，返回该区域图片URL列表。"""
    regions = []
    for kw in SHOT_KW:
        for m in re.finditer(kw, ph, re.I):
            regions.append(m.end())
    best = []
    for pos in regions:
        seg = ph[pos:pos + 2500]
        imgs = re.findall(r'(?:data-src|data-original|src)=["\']([^"\']+)["\']', seg, re.I)
        urls = [u for u in (norm_url(x, base) for x in imgs) if u]
        # 过滤明显 logo/二维码
        urls = [u for u in urls if not re.search(r'logo|qrcode|erweima|ewm|\.ico|/icon', u, re.I)]
        if len(urls) > len(best):
            best = urls
    return best


def extract_fallback_imgs(ph, base):
    imgs = re.findall(r'(?:data-src|data-original|src)=["\']([^"\']+)["\']', ph, re.I)
    out = []
    for x in imgs:
        u = norm_url(x, base)
        if u and not re.search(r'logo|qrcode|erweima|ewm|\.ico|/icon', u, re.I) and u not in out:
            out.append(u)
    return out


def save_screens(aid, urls, maxn=3):
    folder = ASSETS / aid
    folder.mkdir(parents=True, exist_ok=True)
    kept, seen = [], set()
    for iu in urls[:20]:
        data = curl(iu, binary=True)
        if len(data) < 3000:
            continue
        try:
            im = Image.open(io.BytesIO(data)).convert("RGB")
        except Exception:
            continue
        w, h = im.size
        if w < 180 or h < 300 or h / w < 1.3:  # 只要竖版
            continue
        # 排除纯色/低信息启动页
        try:
            colors = len(im.resize((30, 30)).getcolors(900) or [])
        except Exception:
            colors = 30
        if colors < 15:
            continue
        hsh = hashlib.md5(im.resize((16, 16)).tobytes()).hexdigest()
        if hsh in seen:
            continue
        seen.add(hsh)
        if w > 420:
            im = im.resize((420, int(h * 420 / w)), Image.LANCZOS)
        kept.append(im)
        if len(kept) >= maxn:
            break
    saved = []
    for i, im in enumerate(kept, 1):
        p = folder / f"web{i}.webp"
        im.save(p, "WEBP", quality=80, method=6)
        saved.append(str(p.relative_to(SITE)).replace("\\", "/"))
    return saved


results = {}
for aid, url in sources.items():
    # 清理旧的 web 图
    for old in (ASSETS / aid).glob("web*.webp"):
        old.unlink()
    ph = curl(url)
    if len(ph) < 1000:
        ph = curl(url, ua=UA_M)
    urls = extract_region_imgs(ph, url)
    mode = "截图区"
    if len(urls) < 2:
        urls = extract_fallback_imgs(ph, url)
        mode = "兜底"
    saved = save_screens(aid, urls)
    results[aid] = {"url": url, "mode": mode, "candidates": len(urls), "saved": saved}
    print(f"[{aid:18}] {mode} {len(urls):3}候选 -> {len(saved)}张 {'✅' if saved else '❌'}")

json.dump(results, open(ROOT / "data" / "image_fetch_result.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("\n完成 -> data/image_fetch_result.json")
