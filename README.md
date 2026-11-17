# 赚钱App大全 · GitHub + Cloudflare 手机赚钱软件博客

一套**零成本、全自动**的手机赚钱App测评站：数据驱动生成静态站，AI 每日自动写文章，GitHub Actions 自动构建提交，Cloudflare Pages 自动部署 + 搜索引擎推送。

## 定位

| 维度 | 选择 |
|---|---|
| 主题 | 手机软件赚钱（任务赚钱 / 问卷调查 / 看视频 / 看小说 / 游戏试玩 / 手机接单 / 手机电商） |
| 内容生产 | 智谱 GLM 批量生成 + 自动发布 |
| 变现方式 | 联盟营销 / 返利（文中联盟卡片 + 工具库） |
| 技术方案 | 纯静态站 + GitHub + Cloudflare Pages |

## 目录结构

```
博客/
├── data/                      # 数据源（单一事实来源）
│   ├── site.json              # 站点配置：名称、域名、导航、Hero、统计、订阅
│   ├── categories.json        # 分类
│   ├── affiliates.json        # 联盟项目/工具（变现核心）
│   ├── articles.json          # 文章（AI 生成后追加到这里）
│   └── topics.json            # AI 选题队列（done=false 表示待写）
├── scripts/
│   ├── build.py               # 静态站生成器（零依赖）
│   └── generate_articles.py   # 智谱 AI 批量写稿（零依赖）
├── .github/workflows/daily.yml# 每日自动更新流水线
├── site/                      # 构建产物 = CF Pages 部署根目录
│   ├── index.html             # 首页
│   ├── posts/<slug>/          # 文章页
│   ├── categories/            # 分类页
│   ├── tools/                 # 联盟工具库
│   ├── search/                # 站内搜索
│   ├── about/                 # 关于 + 联盟披露 + 免责声明
│   ├── assets/                # CSS / JS
│   ├── sitemap.xml            # 站点地图
│   ├── robots.txt
│   ├── search-index.json      # 搜索索引
│   ├── _headers               # CF 安全头 + 缓存
│   └── _redirects             # 重定向规则
└── README.md
```

## 本地运行

```bash
# 1) 构建静态站（无需安装任何依赖）
python scripts/build.py

# 2) 本地预览（任选其一）
cd site && python -m http.server 8080
# 浏览器打开 http://localhost:8080
```

## AI 生成文章

1. 在 `data/topics.json` 里加选题（`done: false`）。
2. 设置智谱 API Key（**不要写进文件，只用环境变量**）：

```bash
# macOS / Linux / Git Bash
export ZHIPU_API_KEY=你的密钥
# Windows PowerShell
$env:ZHIPU_API_KEY="你的密钥"
```

3. 生成：

```bash
python scripts/generate_articles.py --count 2   # 生成 2 篇
python scripts/generate_articles.py --dry-run   # 调试：只打印提示词
```

生成逻辑：调用智谱 GLM（OpenAI 兼容接口，默认 `glm-4-flash` 免费），返回结构化 JSON，自动去重、校验联盟 ID、追加到 `articles.json`，并把对应选题标记为 `done: true`。

> 想换模型：设置环境变量 `ZHIPU_MODEL`（如 `glm-4-plus`）。想换接口：`ZHIPU_API_URL`。

## 部署到 Cloudflare Pages

**方式 A：GitHub 集成（推荐）**

1. 把本项目推送到 GitHub 仓库。
2. CF 仪表盘 → Workers & Pages → Create → Pages → Connect to Git → 选该仓库。
3. 构建配置：
   - Framework preset：**None**
   - Build command：`python scripts/build.py`
   - Build output directory：`site`
   - Root directory：`/`
   - Environment variables：`PYTHON_VERSION=3.11`（如需要）
4. 保存并部署。之后每次 `git push` 会自动重新构建。

> 注意：CF Pages 默认构建镜像已含 Python。如构建报 Python 版本问题，可在 `wrangler.toml` 或仪表盘指定。

**方式 B：直接上传 site/（不需要构建环境）**

```bash
python scripts/build.py
npx wrangler pages deploy site --project-name=money-apps-hub
```

## 每日自动更新（GitHub Actions）

`.github/workflows/daily.yml` 已配置好：每天 UTC 00:00（北京时间 08:00）自动执行「AI 写稿 → 构建 → 提交 → CF 部署 → 搜索引擎 ping」。

需要在仓库 **Settings → Secrets and variables → Actions** 配置：

| 名称 | 类型 | 说明 |
|---|---|---|
| `ZHIPU_API_KEY` | Secret | 智谱 API Key |
| `SITE_DOMAIN` | Variable | 你的域名，如 `www.example.com`（用于 sitemap ping） |
| `ZHIPU_MODEL` | Variable（可选） | 模型名，默认 `glm-4-flash` |
| `CF_DEPLOY_HOOK` | Secret（可选） | 若不用 GitHub 集成部署，填 CF Deploy Hook URL |

配置好后可先在 Actions 页面手动 **Run workflow** 验证一次。

## SEO 要点（已内置）

- 每页有独立 title / description / canonical / OG 标签
- 文章页输出 JSON-LD（Article / WebSite 结构化数据）
- 自动生成 `sitemap.xml` + `robots.txt`，每日更新后 ping Google / Bing
- 语义化 HTML、图片 emoji、清晰 H1/H2 层级

## 联盟变现合规（重要）

- `affiliates.json` 里的 `url` 现在是占位链接（`example.com/go/xxx`），**上线前务必替换为你的真实联盟链接**。
- 站内在 three 处做了联盟披露：工具库顶部、文章联盟卡片角标、页脚 + 关于页，符合 FTC / 国内广告法对付费推广的披露要求。
- 只推荐真实用过的平台，不要为佣金虚假宣传收益——这是这类站长期活下来的根本。

## 后续可扩展

- 邮件订阅：目前是前端演示，`main.js` 里已留 `fetch('/api/subscribe')` 接口位，可接 CF Worker + KV 存邮箱。
- 反爬/统计：可加 Umami（在 `site.json` 填 `analytics_id`）。
- 多语言：数据源结构清晰，可按 `lang` 字段扩展 i18n。
