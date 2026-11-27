#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bing Webmaster Tools · URL Submission API 主动推送 + 收录数据查询

设计要点：
1. API key 只从环境变量 BING_API_KEY 读取，绝不写进代码或仓库文件。
   （注意：Bing Webmaster API key 与 IndexNow key 是两回事，前者从
    Settings → API Access 获取，一个账号只有一个；后者是放网站根目录的 txt。）
2. 端点用新版 JSON/REST：ssl.bing.com/webmaster/api.svc/json/
   （旧 SOAP/POX 已于 2026-08-31 退役）。
3. 已推送 URL 记录在 data/bing_pushed.json，跨次去重；额度从 API 实时查询。
4. 零第三方依赖（仅标准库），本地与 GitHub Actions 均可运行。
5. key 未配置时优雅跳过（exit 0），不阻断 CI。

用法：
  BING_API_KEY=xxx python scripts/bing_push.py --stats          # 查看收录/抓取/流量数据
  BING_API_KEY=xxx python scripts/bing_push.py --status         # 查提交额度 + 本地推送状态
  BING_API_KEY=xxx python scripts/bing_push.py --dry-run        # 预览待推 URL
  BING_API_KEY=xxx python scripts/bing_push.py --limit 10       # 推送未推过的 URL（最多10条）
  BING_API_KEY=xxx python scripts/bing_push.py --all            # 全量推送（受额度限制）
"""

import os
import sys
import re
import json
import argparse
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE_CFG_PATH = ROOT / "data" / "site.json"
SITEMAP = ROOT / "site" / "sitemap.xml"
STATE_PATH = ROOT / "data" / "bing_pushed.json"
API_BASE = "https://ssl.bing.com/webmaster/api.svc/json"

BLOCK_RE = re.compile(r"<url>(.*?)</url>", re.S)
LOC_RE = re.compile(r"<loc>(.*?)</loc>", re.S)
LASTMOD_RE = re.compile(r"<lastmod>(.*?)</lastmod>", re.S)


def today():
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path, obj):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def get_key():
    return (os.environ.get("BING_API_KEY") or "").strip()


def get_site():
    cfg = read_json(SITE_CFG_PATH, {})
    domain = cfg.get("domain", "").rstrip("/")
    if not domain:
        raise RuntimeError("site.json 缺少 domain 配置")
    return domain


def api(key, method, params=None):
    """调用 Bing Webmaster JSON/REST API，返回解析后的 JSON（含 'd' 包装）。"""
    q = {"apikey": key}
    if params:
        q.update(params)
    url = f"{API_BASE}/{method}?{urllib.parse.urlencode(q)}"
    req = urllib.request.Request(url, headers={"Content-Type": "application/json; charset=utf-8"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace")), resp.status
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            return json.loads(body), e.code
        except Exception:
            return {"error": body[:200]}, e.code


def msdate(v):
    """把 /Date(1794960000000)/ 转成 YYYY-MM-DD（UTC+8）。"""
    m = re.search(r"(\d+)", str(v))
    if not m:
        return str(v)
    dt = datetime.fromtimestamp(int(m.group(1)) / 1000, timezone(timedelta(hours=8)))
    return dt.strftime("%Y-%m-%d")


def collect_urls():
    if not SITEMAP.exists():
        raise RuntimeError("未找到 site/sitemap.xml，请先运行 python scripts/build.py")
    xml = SITEMAP.read_text(encoding="utf-8")
    items = []
    for block in BLOCK_RE.findall(xml):
        m = LOC_RE.search(block)
        if not m:
            continue
        lm = LASTMOD_RE.search(block)
        items.append((m.group(1).strip(), lm.group(1).strip() if lm else ""))
    indexed = list(enumerate(items))
    indexed.sort(key=lambda pair: (pair[1][1], -pair[0]), reverse=True)
    return [url for _, (url, _) in indexed]


def load_state():
    st = read_json(STATE_PATH, {})
    if not isinstance(st, dict):
        st = {}
    st.setdefault("pushed", [])
    st.setdefault("history", [])
    return st


def cmd_stats(key, site):
    print(f"站点: {site}\n")
    # 流量与展现
    res, code = api(key, "GetRankAndTrafficStats", {"siteUrl": site})
    if code == 200 and isinstance(res.get("d"), list):
        print("=== Bing 展现/点击（近 8 天）===")
        print(f"{'日期':<12}{'展现':>6}{'点击':>6}")
        for r in res["d"]:
            print(f"{msdate(r.get('Date')):<12}{r.get('Impressions', 0):>6}{r.get('Clicks', 0):>6}")
        print(f"  展现合计: {sum(r.get('Impressions', 0) for r in res['d'])} | 点击合计: {sum(r.get('Clicks', 0) for r in res['d'])}")
    else:
        print("流量数据获取失败:", res)

    # 抓取统计
    print()
    res, code = api(key, "GetCrawlStats", {"siteUrl": site})
    if code == 200 and isinstance(res.get("d"), list):
        print("=== Bing 抓取统计（近 7 天）===")
        print(f"{'日期':<12}{'抓取页':>8}{'已收录':>8}{'抓取错误':>10}")
        for r in res["d"]:
            print(f"{msdate(r.get('Date')):<12}{r.get('CrawledPages', 0):>8}{r.get('InIndex', 0):>8}{r.get('CrawlErrors', 0):>10}")
        print(f"  抓取页合计: {sum(r.get('CrawledPages', 0) for r in res['d'])} | 抓取错误合计: {sum(r.get('CrawlErrors', 0) for r in res['d'])}")
    else:
        print("抓取数据获取失败:", res)

    # 提交额度
    print()
    res, code = api(key, "GetUrlSubmissionQuota", {"siteUrl": site})
    if code == 200 and isinstance(res.get("d"), dict):
        q = res["d"]
        print(f"=== URL 提交额度 === 每日 {q.get('DailyQuota')} | 每月 {q.get('MonthlyQuota')}")


def cmd_status(key, site):
    st = load_state()
    print(f"站点: {site}")
    print(f"本地已推送 URL: {len(st['pushed'])}")
    if st["history"]:
        print("最近推送:")
        for h in st["history"][-5:]:
            print(f"  {h.get('time')}  请求 {h.get('requested')}  成功 {h.get('success')}")
    print()
    res, code = api(key, "GetUrlSubmissionQuota", {"siteUrl": site})
    if code == 200 and isinstance(res.get("d"), dict):
        q = res["d"]
        print(f"实时额度: 每日 {q.get('DailyQuota')} | 每月 {q.get('MonthlyQuota')}")
    else:
        print("额度查询失败:", res)


def submit(key, site, urls):
    """POST 批量提交 URL。返回 (ok, info)。"""
    payload = json.dumps({"siteUrl": site, "urlList": urls}).encode("utf-8")
    endpoint = f"{API_BASE}/SubmitUrlBatch?{urllib.parse.urlencode({'apikey': key})}"
    req = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return True, f"HTTP {resp.status} {body[:200]}"
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return False, f"HTTP {e.code} {body[:200]}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def cmd_push(key, site, args):
    st = load_state()
    all_urls = collect_urls()
    pushed_set = set(st["pushed"])
    pending = list(all_urls) if args.all else [u for u in all_urls if u not in pushed_set]

    if not pending:
        print(f"无新增 URL（sitemap 共 {len(all_urls)} 条，已全部推送过）")
        return

    batch = pending[: args.limit] if args.limit else pending
    print(f"站点 {site} | sitemap {len(all_urls)} 条 | 待推 {len(pending)} 条 | 本批 {len(batch)} 条")

    if args.dry_run:
        print("[dry-run] 以下 URL 将被推送（未实际请求）：")
        for u in batch:
            print("  " + u)
        return

    ok, info = submit(key, site, [u for u in batch])
    print(("✅ Bing 推送完成: " if ok else "❌ Bing 推送失败: ") + info)
    if ok:
        st["pushed"] = sorted(pushed_set | set(batch))
    st["history"].append({"time": today(), "requested": len(batch), "success": ok, "info": info[:120]})
    save_json(STATE_PATH, st)
    if not ok:
        print("警告: Bing 推送失败，但不阻断流程")


def main():
    ap = argparse.ArgumentParser(description="Bing Webmaster URL 推送与收录数据查询")
    ap.add_argument("--stats", action="store_true", help="查看收录/抓取/流量数据")
    ap.add_argument("--status", action="store_true", help="查提交额度 + 本地推送状态")
    ap.add_argument("--dry-run", action="store_true", help="预览待推 URL")
    ap.add_argument("--all", action="store_true", help="推送 sitemap 全部 URL")
    ap.add_argument("--limit", type=int, default=0, help="本批最多推送条数（0=不限）")
    args = ap.parse_args()

    key = get_key()
    if not key:
        print("未配置 BING_API_KEY，跳过（不影响其他流程）")
        return 0
    try:
        site = get_site()
        if args.stats:
            cmd_stats(key, site)
        elif args.status:
            cmd_status(key, site)
        else:
            cmd_push(key, site, args)
    except Exception as e:
        print(f"执行出错: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
