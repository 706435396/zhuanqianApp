#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
百度搜索资源平台 · API 主动推送

设计要点：
1. token 只从环境变量 BAIDU_PUSH_TOKEN 读取，绝不写进代码或仓库文件。
2. 已推送 URL 记录在 data/baidu_pushed.json，随仓库提交，实现跨次去重。
3. 百度对新站每日额度很低（本站首次实测仅个位数），脚本按 remain 自动分批，
   不浪费额度、不请求超出额度的 URL；跨天自动重置额度认知。
4. 零第三方依赖（仅标准库），本地与 GitHub Actions 均可直接运行。
5. token 未配置时优雅跳过（exit 0），不阻断 CI。

用法：
  python scripts/baidu_push.py --status                 # 查看推送状态
  BAIDU_PUSH_TOKEN=xxx python scripts/baidu_push.py --dry-run   # 预览，不推送
  BAIDU_PUSH_TOKEN=xxx python scripts/baidu_push.py             # 推送未推过的 URL
  BAIDU_PUSH_TOKEN=xxx python scripts/baidu_push.py --limit 5   # 限制本批条数
"""

import os
import sys
import re
import json
import argparse
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE_CFG_PATH = ROOT / "data" / "site.json"
SITEMAP = ROOT / "site" / "sitemap.xml"
STATE_PATH = ROOT / "data" / "baidu_pushed.json"
PUSH_API = "http://data.zz.baidu.com/urls"

BLOCK_RE = re.compile(r"<url>(.*?)</url>", re.S)
LOC_RE = re.compile(r"<loc>(.*?)</loc>", re.S)
LASTMOD_RE = re.compile(r"<lastmod>(.*?)</lastmod>", re.S)


def today():
    return datetime.now().strftime("%Y-%m-%d")


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def get_site():
    """返回 site.json 中的完整域名（带 https://），与百度后台验证值一致。"""
    cfg = load_json(SITE_CFG_PATH, {})
    domain = cfg.get("domain", "").rstrip("/")
    if not domain:
        raise RuntimeError("site.json 缺少 domain 配置")
    return domain


def collect_urls():
    """从 sitemap.xml 读取 (url, lastmod)，按 lastmod 降序（最新优先）。"""
    if not SITEMAP.exists():
        raise RuntimeError("未找到 site/sitemap.xml，请先运行 python scripts/build.py")
    xml = SITEMAP.read_text(encoding="utf-8")
    items = []
    for block in BLOCK_RE.findall(xml):
        m = LOC_RE.search(block)
        if not m:
            continue
        url = m.group(1).strip()
        lm = LASTMOD_RE.search(block)
        lastmod = lm.group(1).strip() if lm else ""
        items.append((url, lastmod))
    # 最新修改的排前面；同一天保持 sitemap 原顺序
    indexed = list(enumerate(items))
    indexed.sort(key=lambda pair: (pair[1][1], -pair[0]), reverse=True)
    return [url for _, (url, _) in indexed]


def load_state():
    st = load_json(STATE_PATH, {})
    st.setdefault("pushed", [])
    st.setdefault("remain", None)
    st.setdefault("date", "")
    st.setdefault("history", [])
    return st


def push_once(token, site, urls):
    """调用百度 API 推送一批 URL，返回解析后的 JSON。"""
    payload = "\n".join(urls) + "\n"
    query = urllib.parse.urlencode({"site": site, "token": token})
    endpoint = f"{PUSH_API}?{query}"
    req = urllib.request.Request(
        endpoint,
        data=payload.encode("utf-8"),
        headers={"Content-Type": "text/plain"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"百度接口 HTTP {e.code}: {body[:300]}")
    try:
        return json.loads(body)
    except Exception:
        raise RuntimeError(f"百度接口返回非 JSON: {body[:300]}")


def cmd_status():
    st = load_state()
    site = get_site()
    print(f"站点:       {site}")
    print(f"已推送 URL: {len(st['pushed'])}")
    print(f"额度记录:   {st['remain'] if st['remain'] is not None else '未知'} (记录日期 {st['date'] or '无'})")
    if st["history"]:
        print("最近推送:")
        for h in st["history"][-5:]:
            print(f"  {h.get('time')}  请求 {h.get('requested')}  成功 {h.get('success')}  剩余 {h.get('remain')}")
    return 0


def cmd_push(args):
    token = (os.environ.get("BAIDU_PUSH_TOKEN") or "").strip()
    if not token:
        print("未配置 BAIDU_PUSH_TOKEN，跳过百度推送（不影响其他流程）")
        return 0

    site = get_site()
    st = load_state()

    # 跨天重置额度认知（百度每日 0 点重置配额）
    if st.get("date") != today():
        st["date"] = today()
        st["remain"] = None

    all_urls = collect_urls()
    pushed_set = set(st["pushed"])
    pending = [u for u in all_urls if u not in pushed_set]

    if args.all:
        # 全量模式：强制推所有 URL（仅用于首次或调试，仍受额度限制）
        pending = list(all_urls)

    if not pending:
        print(f"无新增 URL（sitemap 共 {len(all_urls)} 条，已全部推送过）")
        return 0

    # 额度感知：本批条数 = min(未推数, 用户 limit, 上次剩余额度)
    limit = args.limit
    if st.get("remain") is not None:
        limit = min(limit, int(st["remain"]))
    limit = max(0, limit)
    batch = pending[:limit]

    if not batch:
        print(f"今日额度已用尽（remain={st.get('remain')}），剩余 {len(pending)} 条留待明天")
        return 0

    print(f"站点 {site} | sitemap {len(all_urls)} 条 | 待推 {len(pending)} 条 | 本批 {len(batch)} 条")

    if args.dry_run:
        print("[dry-run] 以下 URL 将被推送（未实际请求）：")
        for u in batch:
            print("  " + u)
        return 0

    result = push_once(token, site, batch)
    success = int(result.get("success", 0))
    remain = result.get("remain")
    not_same = result.get("not_same_site", []) or []
    not_valid = result.get("not_valid", []) or []

    # 只有未被判定为「非本站/不合法」的 URL 才记为已推，避免下次重复踩坑
    bad = set(not_same) | set(not_valid)
    newly_pushed = [u for u in batch if u not in bad]
    st["pushed"] = list(dict.fromkeys(st["pushed"] + newly_pushed))
    if remain is not None:
        st["remain"] = int(remain)
    st["history"].append({
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "requested": len(batch),
        "success": success,
        "remain": remain,
        "not_same_site": len(not_same),
        "not_valid": len(not_valid),
    })
    st["history"] = st["history"][-30:]
    save_json(STATE_PATH, st)

    print(f"✅ 推送完成：成功 {success}/{len(batch)}，当日剩余额度 {remain}")
    if not_same:
        print(f"⚠️  非本站 URL {len(not_same)} 条：{not_same[:3]}")
    if not_valid:
        print(f"⚠️  不合法 URL {len(not_valid)} 条：{not_valid[:3]}")
    if remain is not None and int(remain) <= 0:
        print(f"今日额度已用尽，剩余 {len(pending) - len(batch)} 条留待明天自动推送")
    return 0


def main():
    ap = argparse.ArgumentParser(description="百度搜索资源平台 API 主动推送")
    ap.add_argument("--dry-run", action="store_true", help="只预览，不实际推送")
    ap.add_argument("--all", action="store_true", help="全量模式：连同已推过的 URL 一并推送（受额度限制）")
    ap.add_argument("--limit", type=int, default=10, help="本批最多推送条数（默认 10）")
    ap.add_argument("--status", action="store_true", help="查看推送状态")
    args = ap.parse_args()
    try:
        if args.status:
            return cmd_status()
        return cmd_push(args)
    except Exception as e:
        # CI 中不让推送失败阻断整条流水线
        print(f"⚠️  百度推送跳过：{e}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
