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
│   ├── topics.json            # AI 选题队列（done=false 表示待写）
│   └── wechat_state.json      # 微信草稿同步状态（自动生成，去重防重复推送）
├── scripts/
│   ├── build.py               # 静态站生成器（零依赖）
│   ├── generate_articles.py   # 智谱 AI 批量写稿（零依赖）
│   └── wechat_draft.py        # 微信公众号草稿箱同步（需 requests + pillow）
├── config/
│   ├── wechat.example.json    # 微信配置模板（复制为 wechat.json 后填凭证）
│   └── wechat.json            # 你的真实凭证（gitignore 排除，不推送）
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
   - ⚠️ **Deploy command（部署命令）必须留空！** 这是最容易踩的坑：如果填了 `npx wrangler deploy`（Workers 命令），会报 `Missing entry-point to Worker script` 导致部署失败。Pages 连接 Git 后会自动部署，不需要也不应该填任何部署命令。
4. 保存并部署。之后每次 `git push` 会自动重新构建。

> 注意：CF Pages 默认构建镜像已含 Python。如构建报 Python 版本问题，在仪表盘环境变量里指定 `PYTHON_VERSION=3.11`。
>
> **本仓库故意不放 `wrangler.toml`**：纯静态站由 Pages 直接托管，不需要 Wrangler 配置。若放了 `wrangler.toml`，Pages 的 Wrangler 配置校验（BETA）会读取它并对不受支持的字段（如 `assets`）报错，导致部署失败。
>
> 如果之前填错了 Deploy command：进入项目 → Settings → Builds & deployment → 编辑构建配置 → 清空 Deploy command → 保存并 Retry。

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

## 微信公众号每日推送（草稿箱半自动）

把网站文章同步到公众号草稿箱，最后一步「群发」在公众号后台人工点——既符合微信合规要求，个人订阅号也能用。

### 能力边界（先看这个，少走弯路）

| 能力 | 个人未认证订阅号 |
|---|---|
| 获取 token / 上传图片素材 / 草稿箱增删查 | ✅ 可用 |
| API 自动发布（freepublish）/ 群发 | ❌ 2025-07 起回收，个人主体无法调用 |

所以脚本**只做到「进草稿箱」**，发布必须人工点。这也符合微信《运营规范》2026 版「不得用脚本全自动替代真人发布」的要求。订阅号每天可群发 1 次（每次最多 8 篇），正好匹配每日推送。

### 首次配置

1. 安装依赖：`pip install requests pillow`
2. 复制 `config/wechat.example.json` 为 `config/wechat.json`，填入：
   - `appid` / `appsecret`：微信公众平台 → 设置与开发 → 基本配置 获取
   - `source_url`：站点域名（默认读 site.json，应为 `https://money.72tool.com`）
3. **配置 IP 白名单**（最易踩坑）：公众号后台 → 设置与开发 → 基本配置 → IP 白名单，把运行脚本的公网 IP 加进去。家宽 IP 会变，变动后需重新添加；报错 `40164` 就是这个问题。
   - 想彻底省事：把脚本部署在有固定公网 IP 的小服务器上跑。

> 密钥也可用环境变量 `WECHAT_APPID` / `WECHAT_APPSECRET` 提供（优先级更高），不落盘更安全。`config/wechat.json` 已被 `.gitignore` 排除。

### 常用命令

```bash
# 预览某篇生成的 HTML（不调接口，先看排版对不对）
python scripts/wechat_draft.py --dry-run --slug app-zhongrenbang
# 会写出 _wechat_preview.html，用浏览器打开检查

# 同步最新 1 篇未推送文章到草稿箱（日常用这个）
python scripts/wechat_draft.py --latest 1

# 同步指定文章 / 查看已同步列表 / 清除某篇同步标记
python scripts/wechat_draft.py --slug app-zhongrenbang
python scripts/wechat_draft.py --status
python scripts/wechat_draft.py --reset app-zhongrenbang
```

脚本会自动：Markdown 转微信内联样式 → 运营信息卡/收益示意/真实截图画廊渲染 → 截图上传微信换内部 URL → 上传封面素材 → 建草稿 → 记录状态防重复。合规上会自动**去掉联盟返利直链**、文末加免责声明与「阅读原文」引导。

### 建议的日常节奏

每天 08:00 自动写稿构建后，你手动跑一次 `--latest 1`，然后打开公众号后台 → 草稿箱 → 检查标题封面排版 → 群发。全程约 2 分钟，既自动化了机械活，又守住人工审核关口。

> GitHub Actions 里直接跑微信脚本会遇到 IP 白名单问题（runner 出口 IP 不固定），所以微信同步这一步设计为**本地/固定 IP 手动执行**，不接进每日 Actions。

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
