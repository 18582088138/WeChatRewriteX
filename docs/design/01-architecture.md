# 01 · 总体架构

## 分层视图

```mermaid
flowchart TB
    subgraph UI[前端 Web GUI · PC + 移动 PWA]
        pages[文章列表 / 工作台 / 设置]
        editor[块编辑器 · 素材面板 · 审稿面板]
    end

    subgraph API[API 层 · FastAPI]
        rest[REST Routers]
        sse[SSE 任务进度推送]
        auth[本地访问令牌]
    end

    subgraph PIPE[编排层 Pipeline]
        orch[编排器 Orchestrator]
        queue[任务队列 · SQLite 持久化]
        hooks[Hooks 事件总线]
    end

    subgraph AGENTS[Agent 层]
        collector[资料收集 Agent]
        rewriter[洗稿 Agent]
        reviewer[审稿 Agent]
    end

    subgraph SVC[服务层 Services]
        llm[LLM 路由<br/>litellm + 薄路由层]
        crawl[爬虫适配层<br/>trafilatura / 公众号解析 / Playwright / arXiv]
        search[搜索适配层<br/>Tavily / Bing / arXiv API]
        media[媒体处理<br/>下载 / pHash 去重 / 水印检测 / yt-dlp]
        rag[素材检索<br/>全文 + 向量]
        cards[卡片生成<br/>HTML 模板 → Playwright 截图]
        pub[发布适配层<br/>Publisher 插件]
    end

    subgraph STORE[存储层]
        db[(SQLite<br/>索引 / 状态 / 版本)]
        fs[(文件素材库<br/>data/library/)]
        cfg[配置<br/>.env + settings.yaml]
    end

    UI --> API --> PIPE --> AGENTS --> SVC --> STORE
    AGENTS <--> hooks
```

## 技术选型

| 层 | 选型 | 理由 |
|---|---|---|
| 后端 | Python 3.12 + FastAPI + Uvicorn | 与 conda `xkd_env_py312` 对齐；FastAPI 自带 OpenAPI 文档，便于调试 |
| 数据库 | SQLite（WAL 模式） | 本地单用户零运维；状态、版本、索引一库搞定 |
| 任务队列 | 进程内 asyncio 队列 + SQLite `jobs` 表持久化 | 本地单用户不需要 Celery/Redis；重启可恢复 |
| LLM 调度 | **litellm SDK** + 自建薄路由层 | litellm 统一 100+ 提供商接口（`provider/model` 字符串路由）；薄层实现渠道优先级、失败降级、token 成本日志——不必自建网关，借鉴 new-api 的「渠道优先级 + 亲和性」思想即可 |
| 结构化输出 | Pydantic + JSON Schema（约束解码/函数调用） | 三个 Agent 的输出都必须 schema 化，杜绝「模型随口一说」 |
| 爬虫 | trafilatura（主）+ 自写公众号解析器 + Playwright（兜底） | 公众号正文是静态 HTML，直接解析 `#js_content` 节点比通用提取器还原更准；JS 重页面（X、部分官网）走 Playwright |
| 论文 | arXiv API + pypdf | 新模型/论文类要闻的标准来源 |
| 视频 | yt-dlp（X / B站 支持好）+ 微博走 Playwright 抓包补位 | yt-dlp 的微博 extractor 脆弱，需要降级链 |
| 查重 | SimHash（字符 n-gram  shingles，无第三方依赖）+ 向量余弦 | 字面 + 语义双阈值，见 `02` 审稿 |
| 向量 | **OpenAI 兼容 embedding API**（火山方舟 doubao-embedding 等）；不可用时降级纯 FTS5 | 已拍板（2026-10-24）：不本地装 torch 大模型，接口预留本地 ONNX 扩展 |
| 卡片组图 | 自写 HTML 模板 + Playwright 截图出 PNG | 参考 guizang-social-card-skill 的管线模式（AGPL，只借鉴不自用代码） |
| 前端 | Vue 3 + Vite + Pinia + Vue Router + TailwindCSS + PWA | 响应式 + 可「添加到主屏幕」，覆盖 PC 与手机浏览器 |
| 前端编辑器 | 自研块编辑器（预览默认 / 双击编辑） | 段落级再生成、图片替换天然落在块模型上，见 `04` |
| 公众号排版 | doocs/md 主题 CSS 思路（WTFPL 协议） | Markdown → 公众号排版 HTML 的成熟方案 |

## 后端包结构（目标形态）

```
app/
├── main.py                  # FastAPI 入口，挂载路由与静态前端
├── core/
│   ├── config.py            # 三层配置合并: 默认 < settings.yaml < UI(DB)
│   ├── models.py            # Pydantic 领域模型
│   ├── statemachine.py      # Article 状态机 (见 02)
│   ├── events.py            # 事件定义 + Hook 触发
│   └── errors.py
├── agents/
│   ├── base.py              # AgentBase: prompt 渲染 / 模型选择 / schema 校验 / 重试
│   ├── collector/           # 资料收集 Agent
│   ├── rewriter/            # 洗稿 Agent
│   └── reviewer/            # 审稿 Agent
├── services/
│   ├── llm/                 # litellm 薄路由: 渠道注册 / fallback / 成本日志
│   ├── crawl/               # 爬虫插件: base.py + trafilatura_/wechat_mp_/playwright_/arxiv_/x_
│   ├── search/              # 搜索插件: tavily_/bing_/arxiv_
│   ├── media/               # 图片下载去重、水印检测、yt-dlp 封装
│   ├── rag/                 # 素材索引与检索 (全文 + 向量)
│   ├── cards/               # 小红书卡片: 模板渲染 + Playwright 截图
│   ├── dedup/               # simhash / minhash / 向量相似度
│   └── publish/             # Publisher 插件: wechat_mp_api_ / rpa_ / exporter_
├── pipeline/
│   ├── orchestrator.py      # 阶段推进、auto/manual 模式
│   ├── queue.py             # SQLite 任务队列
│   └── hooks.py             # Hook 加载与执行 (shell / python callable)
├── storage/                 # SQLite DAO + 文件库读写
├── api/                     # routers: articles/materials/drafts/reviews/publish/settings/jobs
├── plugins/                 # 第三方插件落点 (目录扫描 + entry_points)
└── logging_setup.py

web/                         # 前端源码 (Vue3 + Vite)
config/                      # 一切可手动调整的提示词与参数 (拍板 2026-10-24)
├── settings.yaml            # 非密钥参数 (窗口/阈值/模型档位/并发/hooks)
├── prompts/                 # 版本化 Jinja2 模板, 按 Agent 分目录, 每版带 changelog
│   ├── collector/  rewriter/  reviewer/
└── styles/                  # 风格包 (默认 tech-evangelist)
data/                        # 运行期数据, gitignore
├── app.db
├── library/                 # 素材库 (见 03)
├── drafts/                  # 文案版本落盘
└── exports/                 # 平台导出包
docs/design/                 # 本文档集
.env                         # 密钥 (不进 git)
```

## LLM 路由层设计

> 实现细化（2026-10-24）：一阶段先实现内置 OpenAI 兼容客户端（DeepSeek / 火山方舟 / OpenAI 均兼容，轻量、可无网络单测），接口与 litellm 的 `provider/model` 路由约定保持一致；litellm 作为可选后端留扩展口。

配置示例（`config/settings.yaml`）：

```yaml
llm:
  channels:                      # 渠道 = 某 provider 的一组 key
    - name: deepseek-main
      provider: deepseek
      env_key: DEEPSEEK_API_KEY
      priority: 1
    - name: ark-backup
      provider: volcengine       # 火山方舟, OpenAI 兼容
      env_key: ARK_API_KEY
      priority: 2
  routing:                       # 按用途分配模型档位
    summarize:   { model: deepseek/deepseek-chat,  temperature: 0.3 }
    rewrite:     { model: deepseek/deepseek-chat,  temperature: 0.7 }
    review:      { model: deepseek/deepseek-reasoner, temperature: 0.2 }  # 审稿可用推理模型
    vision:      { model: volcengine/doubao-vision, temperature: 0.2 }    # 图片水印/内容判断
  fallback: [deepseek-main, ark-backup]   # 失败按序降级
  cost_log: true                 # 每次调用记录 tokens 与估算成本
```

要点：

- **按用途而非按 Agent 分配模型**：同一 Agent 内「摘要用便宜档、成稿用强档」；审稿用不同渠道做交叉验证可降低同源盲区。
- 每次调用落 `llm_calls` 表（渠道、模型、tokens、耗时、所属任务/阶段），成本可审计。
- 结构化输出失败（schema 校验不过）自动带错误信息重试一次，再失败进入人工可见的失败态。

## 扩展机制（重点：这是产品级的可扩展设计）

### 1. 插件（Plugins）

四类插件点，统一约定：目录 `plugins/<name>/` 含 `plugin.yaml`（名称、类型、版本、入口）+ 实现文件；启动时扫描注册。

| 插件类型 | 接口 | 内置实现 |
|---|---|---|
| Crawler | `can_handle(url) -> bool` / `fetch(url) -> RawArticle` | trafilatura、wechat_mp、arxiv、playwright_generic |
| Searcher | `search(query, window) -> list[SearchResult]` | tavily、bing、arxiv |
| Publisher | `capabilities()` / `push(variant) -> PushResult` | 公众号 API、RPA 驱动、导出包（见 `05`） |
| CardTheme | 模板目录（HTML+CSS+分页规则） | 2~3 套小红书主题 |

### 2. Hooks（事件钩子）

流水线关键事件可挂用户脚本（`settings.yaml` 注册 shell 命令或 Python callable）：

```
article.added        collect.finished      rewrite.finished
review.finished      draft.finalized       publish.finished   job.failed
```

典型用途：自动推进下一阶段（`auto_pipeline: true` 时等价于内部推进）、定稿后微信/邮件通知、每次落盘后自动 git commit 备份。

### 3. MCP（双向）

- **作为 MCP Client**：消费外部工具服务器（如 tavily-mcp、playwright-mcp），把「搜索」「浏览器动作」外包给成熟 MCP 服务，配置里启用即可。
- **作为 MCP Server**：把素材库检索、草稿读写、发布推送暴露为 MCP 工具（参考 XHS-Downloader 的 CLI/API/MCP 三入口形态），让 ZCode / Claude 等外部 Agent 也能驱动本应用。

### 4. 风格包（Style Packs）

写作风格做成可热插拔的目录包（类似「技能包」）：

```
config/styles/tech-evangelist/   # 默认: 轻松诙谐+严谨科学的技术传火人/布道师人设
├── style.yaml                   # 名称、适用平台、词数区间、温度
├── system.md                    # 系统提示词
├── rules.md                     # 风格规则 (链接到 06 文档的规则集)
├── banlist.txt                  # 禁用词/AI 套话表
├── fewshots/                    # 2~4 篇范文对 (原文→成稿), 从范文库蒸馏
└── layout/                      # 配套排版/卡片模板
```

设置中按平台绑定风格包；调优方法见 `06-style-guide.md`。

## 并发与运行模型

- 本地单用户：一个编排器协程 + 有界并发（默认 2 个 LLM 阶段任务、4 个下载任务），避免触发 LLM 限流与网站反爬。
- 每个阶段任务 = `jobs` 表一行（类型、payload、状态、重试次数、结果引用），崩溃重启后可续跑。
- 长任务（收集、洗稿、审稿、卡片渲染）通过 SSE 向前端推送进度事件。

## 安全与边界

- 密钥只读 `.env`；`settings.yaml` 与 DB 里**不存密钥**，UI 设置页只显示掩码。
- 所有 outbound 请求（爬取/搜索/发布）走统一的 `http_client`，带 UA 池、超时、限速与重试。
- 本地 API 默认绑定 `127.0.0.1`，如需手机访问开局域网模式并启用访问令牌。

## 开放问题

1. 向量索引用 sqlite-vec 还是纯 numpy？（倾向 sqlite-vec，待 M1 验证其 Windows 轮子可用性）
2. 是否需要多用户？（当前设计按单用户；若未来要多人协作，认证与数据隔离需提前留口）
