#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
清除 Cloudflare 缓存（用于站长验证文件的旧 404 缓存等场景）。

用法：
  CF_API_TOKEN=你的token python scripts/cf_purge.py
  CF_API_TOKEN=你的token python scripts/cf_purge.py --domain money.72tool.com

所需 token 权限：Zone → Cache → Purge（只需这一项），Zone Resources 选 72tool.com。
token 仅从环境变量读取，不落盘、不写日志。
"""

import os
import sys
import json
import argparse
import urllib.request
import urllib.error

API = "https://api.cloudflare.com/client/v4"


def api(token, path, method="GET", data=None):
    url = API + path
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(
        url, data=body, method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode("utf-8", errors="replace"))


def main():
    ap = argparse.ArgumentParser(description="清除 Cloudflare 缓存")
    ap.add_argument("--domain", default="money.72tool.com", help="要清缓存的域名")
    args = ap.parse_args()

    token = (os.environ.get("CF_API_TOKEN") or "").strip()
    if not token:
        print("未设置 CF_API_TOKEN，无法清缓存")
        return 1

    # 从完整域名逐级向上找 zone（money.72tool.com → 72tool.com）
    parts = args.domain.split(".")
    zone = None
    for i in range(len(parts) - 1):
        zone_name = ".".join(parts[i:])
        res = api(token, f"/zones?name={zone_name}")
        if res.get("success") and res.get("result"):
            zone = res["result"][0]
            break

    if not zone:
        print(f"未找到 {args.domain} 对应的 zone（检查 token 是否有该域权限）")
        return 1

    print(f"找到 zone: {zone['name']} ({zone['id']})")
    res = api(token, f"/zones/{zone['id']}/purge_cache", "POST", {"purge_everything": True})
    if res.get("success"):
        print("✅ 缓存已清除（Purge Everything）")
        return 0
    print("❌ 清除失败:", json.dumps(res.get("errors", []), ensure_ascii=False))
    return 1


if __name__ == "__main__":
    sys.exit(main())
