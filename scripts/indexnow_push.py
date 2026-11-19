#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IndexNow 主动推送（零依赖，仅标准库）

把站点新增/更新的 URL 推送给 IndexNow，Bing / Yandex / Seznam / Naver 等
参与引擎会同步抓取。相比 Bing URL Submission API 的优势：
  - 无需申请 API key、无账号绑定、无每日配额申请流程
  - key 以文件形式放在站点根目录，证明域名所有权
  - 一次推送同步给所有参与引擎

协议要点（https://www.indexnow.org）：
  - 在域名根目录托管 key 文件：<key>.txt，内容就是 key（8~128 位字母数字连字符）
  - POST JSON 到 https://api.indexnow.org/indexnow
  - 200/202 = 接收成功；403 = key 文件无效；422 = URL 不属于该 host；429 = 频率限制

设计原则：
  - key 从 data/indexnow_key.txt 读取（与 static/<key>.txt 内容一致），不硬编码
  - 已推送 URL 记在 data/indexnow_pushed.json，避免重复推送同一批
  - 只推 sitemap 里 lastmod 为本批新增/最近的 URL，不每天全量推（全量推会被忽略）
  - 无 key 文件则优雅跳过，不阻断 CI

用法：
  python scripts/indexnow_push.py --status          # 查看状态
  python scripts/indexnow_push.py --dry-run         # 预览待推 URL，不发请求
  python scripts/indexnow_push.py --limit 10        # 实际推送（最多10条）
  python scripts/indexnow_push.py --all             # 推送 sitemap 全部 URL（首次初始化用）
"""

import argparse
import json
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE_CFG_PATH = ROOT / "data" / "site.json"
SITEMAP = ROOT / "site" / "sitemap.xml"
KEY_PATH = ROOT / "data" / "indexnow_key.txt"
STATE_PATH = ROOT / "data" / "indexnow_pushed.json"
ENDPOINT = "https://api.indexnow.org/indexnow"

LOC_RE = re.compile(r"<loc>(.*?)</loc>", re.S)
LASTMOD_RE = re.compile(r"<lastmod>(.*?)</lastmod>", re.S)


def today():
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).strftime("%Y-%m-%d")


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def get_site():
    cfg = load_json(SITE_CFG_PATH, {})
    domain = cfg.get("domain", "").rstrip("/")
    if not domain:
        raise RuntimeError("site.json 缺少 domain 配置")
    if domain.startswith("http://") or domain.startswith("https://"):
        domain = re.sub(r"^https?://", "", domain)
    return domain


def load_key():
    """读取 IndexNow key。优先环境变量，其次 data/indexnow_key.txt。"""
    import os
    key = os.environ.get("INDEXNOW_KEY", "").strip()
    if key:
        return key
    try:
        return KEY_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def collect_urls():
    """从 sitemap.xml 读取 (url, lastmod)，按 lastmod 降序（最新优先）。"""
    if not SITEMAP.exists():
        raise RuntimeError("未找到 site/sitemap.xml，请先运行 python scripts/build.py")
    xml = SITEMAP.read_text(encoding="utf-8")
    blocks = re.findall(r"<url>(.*?)</url>", xml, re.S)
    items = []
    for b in blocks:
        loc = LOC_RE.search(b)
        if not loc:
            continue
        url = loc.group(1).strip()
        lm = LASTMOD_RE.search(b)
        lastmod = lm.group(1).strip() if lm else ""
        items.append((url, lastmod))
    items.sort(key=lambda x: x[1], reverse=True)
    return items


def load_state():
    st = load_json(STATE_PATH, {})
    if not isinstance(st, dict):
        st = {}
    st.setdefault("pushed", [])
    st.setdefault("last_push_date", "")
    st.setdefault("last_result", {})
    return st


def push_once(key, host, key_location, urls):
    """POST 批量 URL 到 IndexNow，返回 (ok, 响应信息)。"""
    payload = {
        "host": host,
        "key": key,
        "keyLocation": key_location,
        "urlList": urls,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT,
        data=data,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "money-apps-indexnow/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            return True, f"HTTP {resp.status} {body[:300]}"
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        return False, f"HTTP {e.code} {body[:300]}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def cmd_status():
    site = get_site()
    key = load_key()
    st = load_state()
    items = collect_urls()
    print(f"站点: {site}")
    print(f"IndexNow key: {'已配置 (' + key[:8] + '...)' if key else '未配置 ❌'}")
    print(f"key 文件: /{key}.txt" if key else "key 文件: 无")
    print(f"sitemap URL: {len(items)} 条")
    print(f"已推送记录: {len(st['pushed'])} 条")
    print(f"最近推送日期: {st.get('last_push_date') or '从未'}")
    print(f"最近结果: {st.get('last_result') or '无'}")


def cmd_dry_run(args):
    site = get_site()
    key = load_key()
    items = collect_urls()
    st = load_state()
    pushed = set(st["pushed"])
    pending = [(u, lm) for u, lm in items if u not in pushed]
    if args.all:
        batch = items[: args.limit] if args.limit else items
    else:
        batch = pending[: args.limit] if args.limit else pending
    print(f"[DRY RUN] 站点 {site} | key {'有' if key else '无'} | sitemap {len(items)} 条 | 待推 {len(pending)} 条")
    print(f"[DRY RUN] 本次将推送 {len(batch)} 条:")
    for u, lm in batch:
        print(f"  - {u}  (lastmod {lm})")


def cmd_push(args):
    site = get_site()
    key = load_key()
    if not key:
        print("未配置 IndexNow key（data/indexnow_key.txt 或 INDEXNOW_KEY 环境变量），跳过推送")
        return

    items = collect_urls()
    st = load_state()
    pushed = set(st["pushed"])

    if args.all:
        candidates = items
    else:
        candidates = [(u, lm) for u, lm in items if u not in pushed]

    if not candidates:
        print("无待推送 URL（sitemap 里的 URL 都已推过）")
        return

    batch = candidates[: args.limit] if args.limit else candidates
    urls = [u for u, _ in batch]
    key_location = f"https://{site}/{key}.txt"

    print(f"站点 {site} | sitemap {len(items)} 条 | 候选 {len(candidates)} 条 | 本批 {len(urls)} 条")
    print(f"推送到 {ENDPOINT} | keyLocation={key_location}")

    ok, info = push_once(key, site, key_location, urls)
    print(("✅ 推送完成: " if ok else "❌ 推送失败: ") + info)

    if ok:
        st["pushed"] = sorted(pushed | set(urls))
        st["last_push_date"] = today()
        st["last_result"] = {"success": True, "count": len(urls), "info": info[:200]}
    else:
        st["last_result"] = {"success": False, "count": len(urls), "info": info[:200]}
    save_json(STATE_PATH, st)

    # 不因推送失败阻断 CI
    if not ok:
        print("警告: IndexNow 推送失败，但不阻断流程")


def main():
    ap = argparse.ArgumentParser(description="IndexNow 主动推送")
    ap.add_argument("--status", action="store_true", help="查看状态")
    ap.add_argument("--dry-run", action="store_true", help="预览，不发请求")
    ap.add_argument("--all", action="store_true", help="推送 sitemap 全部 URL（首次初始化用）")
    ap.add_argument("--limit", type=int, default=0, help="本批最多推送条数（0=不限）")
    args = ap.parse_args()

    try:
        if args.status:
            cmd_status()
        elif args.dry_run:
            cmd_dry_run(args)
        else:
            cmd_push(args)
    except Exception as e:
        print(f"执行出错: {type(e).__name__}: {e}")
        sys.exit(0)  # 不阻断 CI


if __name__ == "__main__":
    main()
