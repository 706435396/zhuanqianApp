#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 批量文章生成器（智谱 GLM，OpenAI 兼容接口）—— 赚钱App大全

从 topics.json 读取待写选题，调用智谱 API 生成结构化文章，去重后追加到 data/articles.json。
API Key 从环境变量 ZHIPU_API_KEY 读取（不落盘、不写死）。

用法：
    export ZHIPU_API_KEY=你的密钥          # Windows PowerShell: $env:ZHIPU_API_KEY="你的密钥"
    python scripts/generate_articles.py            # 按 topics.json 生成全部待写选题
    python scripts/generate_articles.py --count 2  # 本次只生成 2 篇（每日自动更新推荐）
    python scripts/generate_articles.py --dry-run  # 只构造提示词，不调用 API（调试用）

依赖：仅标准库（用 urllib 调 HTTP，无需 pip install）
"""
import os
import re
import json
import time
import argparse
import random
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
ARTICLES_FILE = DATA / "articles.json"
TOPICS_FILE = DATA / "topics.json"
CATEGORIES_FILE = DATA / "categories.json"
AFFILIATES_FILE = DATA / "affiliates.json"

API_KEY = os.environ.get("ZHIPU_API_KEY", "")
# 智谱 OpenAI 兼容端点，GLM-4-Flash 免费；可按需要换成 GLM-4-Plus 等
API_URL = os.environ.get("ZHIPU_API_URL", "https://open.bigmodel.cn/api/paas/v4/chat/completions")
MODEL = os.environ.get("ZHIPU_MODEL", "glm-4-flash")

EMOJIS = ["💰", "🚀", "📈", "💡", "🎯", "🛠️", "📱", "🔥"]
COLORS = ["#4f46e5", "#7c3aed", "#0891b2", "#16a34a", "#ea580c", "#db2777", "#2563eb", "#ca8a04"]


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def load_json(path, default):
    if not path.exists():
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def slugify(text):
    """生成 URL slug：英文数字连字符，中文保留。"""
    s = re.sub(r"[^\w\u4e00-\u9fa5]+", "-", text.strip().lower()).strip("-")
    return s[:40] or ("post-" + datetime.now().strftime("%Y%m%d%H%M%S"))


def now_date():
    return datetime.now().strftime("%Y-%m-%d")


def build_prompt(topic, categories, affiliates):
    """构造生成提示词，要求模型返回严格 JSON。"""
    cat_list = "、".join(f"{c['slug']}({c['name']})" for c in categories)
    aff_lines = "\n".join(
        f"  - ID={a['id']}，名称={a['name']}，类型={a['type']}" for a in affiliates
    )
    return f"""你是一个专业的手机赚钱App测评编辑，擅长写「普通人用手机就能做」的实操干货文章。
请根据以下选题写一篇中文文章。

【选题】
标题方向：{topic.get('title','')}
分类：{topic.get('category','')}（可选分类：{cat_list}）
关键词：{', '.join(topic.get('keywords', []))}
写作角度：{topic.get('angle','')}

【可用的手机赚钱App】（如文章相关，可在正文中用 [[affiliate:ID]] 插入下载推荐卡片；不相关就不要插）
{aff_lines}

【写作要求】
1. 口语化、接地气，像有经验的朋友在分享，不要官方腔、不要 AI 味。
2. 结构：用 ## 分小标题；包含具体步骤、数字、清单；至少有一个 > 引用块强调重点。
3. 必须讲清这款App的赚钱路径、金币/收益换算、提现门槛与到账速度。
4. 正文 1200-1800 字，段落短，多用短句。
5. 必须包含「避坑」或「注意事项」相关内容。
6. 如确需推荐上面的App，用独占一行的 [[affiliate:ID]] 插入，不要编造 ID。
7. 不要写虚假收益承诺（如「日入过万」），不要涉及违法违规或传销内容。

【输出格式】只返回一个 JSON 对象，不要任何多余文字、不要 markdown 代码块包裹：
{{
  "title": "吸引人的文章标题（20字以内）",
  "excerpt": "一句话摘要（50字以内）",
  "content": "Markdown 格式正文（用 ## 做小标题）",
  "tags": ["标签1", "标签2", "标签3", "标签4"],
  "read_time": 8
}}"""


def call_zhipu(prompt, retries=3):
    """调用智谱 API，返回 content 字符串。失败重试。"""
    if not API_KEY:
        raise RuntimeError("未设置环境变量 ZHIPU_API_KEY，无法调用 API。")

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "你是一个严谨的中文自媒体写作助手，只输出合法的 JSON。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.8,
        "max_tokens": 3000,
    }
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
    }

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(API_URL, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=90) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            return body["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="ignore")
            last_err = f"HTTP {e.code}: {detail[:200]}"
        except Exception as e:
            last_err = str(e)
        print(f"  ⚠️ 第 {attempt} 次调用失败：{last_err}，重试中…")
        time.sleep(2 * attempt)
    raise RuntimeError(f"API 调用失败（已重试 {retries} 次）：{last_err}")


def parse_article(raw, topic, categories):
    """清洗模型输出，校验并补齐字段。"""
    text = raw.strip()
    # 去掉可能的代码块包裹
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    data = json.loads(text)

    if not data.get("title") or not data.get("content"):
        raise ValueError("生成结果缺少 title 或 content")

    category = topic.get("category", categories[0]["slug"])
    valid_slugs = {c["slug"] for c in categories}
    if category not in valid_slugs:
        category = categories[0]["slug"]

    # 校验联盟 ID，剔除不存在的
    valid_aff = {a["id"] for a in load_json(AFFILIATES_FILE, [])}
    content = data["content"]
    found_ids = re.findall(r"\[\[affiliate:([^\]]+)\]\]", content)
    affiliate_ids = [i for i in found_ids if i in valid_aff]
    for bad in set(found_ids) - valid_aff:
        content = content.replace(f"[[affiliate:{bad}]]", "")

    try:
        read_time = int(data.get("read_time", 8))
    except Exception:
        read_time = 8

    art = {
        "slug": slugify(data["title"]),
        "title": data["title"].strip(),
        "excerpt": data.get("excerpt", "").strip(),
        "category": category,
        "tags": [str(t) for t in data.get("tags", [])][:5],
        "date": now_date(),
        "updated": now_date(),
        "author": "赚钱App大全编辑部",
        "read_time": max(3, min(read_time, 20)),
        "emoji": random.choice(EMOJIS),
        "color": random.choice(COLORS),
        "featured": False,
        "views": 0,
        "affiliate_ids": list(dict.fromkeys(affiliate_ids)),
        "content": content,
    }
    return art


def main():
    parser = argparse.ArgumentParser(description="AI 批量生成手机赚钱App测评文章（智谱 GLM）")
    parser.add_argument("--count", type=int, default=0, help="本次最多生成几篇（0=全部待写）")
    parser.add_argument("--dry-run", action="store_true", help="只打印提示词，不调用 API")
    args = parser.parse_args()

    topics = load_json(TOPICS_FILE, [])
    categories = load_json(CATEGORIES_FILE, [])
    affiliates = load_json(AFFILIATES_FILE, [])
    articles = load_json(ARTICLES_FILE, [])

    pending = [t for t in topics if not t.get("done")]
    if args.count > 0:
        pending = pending[: args.count]
    if not pending:
        print("✅ 没有待写选题。请先在 data/topics.json 添加选题，或把已完成选题的 done 改回 false。")
        return

    print(f"📝 本次待生成 {len(pending)} 篇，模型：{MODEL}")

    newly_written = []
    for idx, topic in enumerate(pending, 1):
        print(f"\n[{idx}/{len(pending)}] {topic.get('title','(无标题)')}")
        prompt = build_prompt(topic, categories, affiliates)
        if args.dry_run:
            print("--- DRY RUN PROMPT ---")
            print(prompt[:800] + "\n...\n")
            continue
        try:
            raw = call_zhipu(prompt)
            art = parse_article(raw, topic, categories)
            # 去重：按 slug 和标题
            if any(a["slug"] == art["slug"] or a["title"] == art["title"] for a in articles):
                print("  ⏭️ 已存在相同文章，跳过。")
            else:
                articles.insert(0, art)
                newly_written.append(art)
                print(f"  ✅ 生成成功：《{art['title']}》({len(art['content'])} 字)")
        except Exception as e:
            print(f"  ❌ 生成失败：{e}")
            continue

        # 标记选题完成
        topic["done"] = True
        time.sleep(1)  # 轻微限速，避免触发频率限制

    if newly_written:
        save_json(ARTICLES_FILE, articles)
        save_json(TOPICS_FILE, topics)
        print(f"\n🎉 已追加 {len(newly_written)} 篇新文章到 articles.json")
        print("   下一步：python scripts/build.py 重新构建站点")
    elif not args.dry_run:
        save_json(TOPICS_FILE, topics)
        print("\n本次没有新增文章。")


if __name__ == "__main__":
    main()
