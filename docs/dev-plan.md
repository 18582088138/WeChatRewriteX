# 开发计划（M1 · 本地 MVP）

> 依据 `docs/design/` 与 2026-10-24 拍板结论制定。目标：PC 本地可用的完整闭环——录入链接 → 收集 → 创作 → 审稿 → 人工编辑定稿 → 导出多平台发布包。

## 切片与验收

| # | 切片 | 产物 | 验收 |
|---|---|---|---|
| S0 | 脚手架 | `.gitignore` `.env.example` `requirements.txt` `config/` git init | 目录结构与 01 文档一致 |
| S1 | 后端核心 | `app/core`（配置三层合并、块模型、状态机、事件）+ `app/storage`（schema.sql、DAO、素材库读写） | 单测：配置覆盖优先级、块操作、状态机合法迁移、DAO CRUD |
| S2 | 服务层·基础 | LLM 路由（OpenAI 兼容客户端、fallback、成本日志）、embedding（API/Null 两态）、SimHash 查重 | FakeServer 单测 + 查重阈值单测 |
| S3 | 服务层·采集 | 爬虫插件（wechat_mp / trafilatura / arxiv / fixture）、搜索插件（tavily / null）、媒体下载（pHash、Referer、水印启发式）、FTS5 检索 | fixture HTML 抓取单测；公众号解析器用样例 HTML 验证 |
| S4 | Agent | base（prompt 渲染 + schema 校验 + 重试）、collector、rewriter、reviewer；`config/prompts/` 模板；`config/styles/tech-evangelist/` 风格包 | FakeLLM 脚本化输出跑通三 Agent；审稿六维 checklist 结构校验 |
| S5 | 流水线 | jobs 队列（线程 + SQLite 持久化）、编排器（manual/auto）、SSE 事件 | API 触发收集，状态机推进与事件推送可观测 |
| S6 | API | articles/materials/drafts/reviews/publish/settings/jobs 路由 + SSE | FastAPI TestClient smoke：全路由 200/语义正确 |
| S7 | 卡片组图 | 主题 HTML（3:4 1080×1440）、浏览器内自动分页、溢出校验、逐页截图 | 用样例 DraftDoc 出 PNG 页组，无溢出 |
| S8 | 发布包导出 | exporter 插件：公众号（HTML+图）、小红书（卡片 PNG+正文）、微博（短文+图）、X（推文串） | 导出目录结构完整，文本可直接复制 |
| S9 | 前端 | 文章列表（三态）、工作台四 tab（素材/创作/审稿/发布）、块编辑器（预览默认、双击编辑、块级 AI 操作、换图）、设置页 | `npm run build` 通过；本地起服务人工走查主流程 |
| S10 | 范文蒸馏 | 抓取 14 篇范文 → 风格特征写入风格包（网络允许时；失败则手工规则版先行） | 风格包 fewshots 非空或有手工基线 |
| S11 | 文档 | `docs/api.md`、`docs/user-manual.md`、README 更新 | 与设计文档交叉引用一致 |

## 关键实现决策（对 01 文档的细化）

1. **LLM 客户端**：一阶段内置 OpenAI 兼容异步客户端（DeepSeek/Ark/OpenAI 通用），保持 `provider/model` 路由约定；litellm 留扩展口。理由：减依赖、可离线单测。
2. **embedding**：`ApiEmbedder`（OpenAI 兼容 `/embeddings`）+ `NullEmbedder`（纯 FTS 降级），不引入 torch。
3. **DB 访问**：同步 `sqlite3` + FastAPI 同步路由（threadpool），WAL；不引 SQLAlchemy。
4. **任务队列**：后台线程 + `queue.Queue` + `jobs` 表持久化，崩溃可恢复；不引 Celery/Redis。
5. **查重**：自实现字符 n-gram SimHash + Jaccard，不引 jieba/simhash 包。
6. **Taste skill**：环境无此 skill，GUI 品质用设计 token + 组件规范保证。
7. **范文抓取**：wechat_mp 解析器直接复用；X 账号页（@laobaishare）无法无凭据抓取，仅作人工风格参考记录。

## 环境

- 后端：conda `xkd_env_py312`（Python 3.12.14 已验证）
- 前端：Node v22.16.0 + npm 10.9.2（无 pnpm）
- git 本地提交（无 gh CLI，GitHub 远程待配）
- LLM/搜索/embedding 密钥：`.env`（用户配置；无 key 时 Agent 流程以 FakeLLM 跑通逻辑，真实生成待 key 就位）

## 第二轮修订（2026-10-24 用户反馈 8 条，全部落实）

| # | 反馈 | 落实 |
|---|---|---|
| 1 | 安装 taste-skill 并重设计 GUI | 已装至 `~/.zcode/skills/taste-skill`；按 app-screen 规范重设计：1px 边线代替阴影、近黑主按钮、朱红 accent 仅用于品牌/当前态/关键数据、词色三层、去渐变去 emoji、列表改分隔行、统计改分隔条 |
| 2 | 收集 Agent 没有多元化素材 | 新增 DuckDuckGo（零配置网络搜索兜底）+ arXiv 论文搜索器 + Pexels/Pixabay 可商用图/视频补充（用 .env 已有 key）；真实文章验证：5 参考 + 20 图 |
| 3 | 素材落盘统一文件夹、标题命名、分项保存 | `data/library/articles/<标题_短id>/{原文,参考,图片,视频,文档,inbox,exports}`；标题后到自动迁移；发布包并入文章文件夹；图片按内容嗅探真实扩展名 |
| 4 | 创作必须配图 | LLM 配图 + 兜底：无图块时按序自动补插（第二段后/2/3 处）；水印图可用仅打标 |
| 5 | 标题候选/一句话/关键词独立框 | 编辑器侧栏三个独立编辑框；后端新增 `update_meta` 操作（含 title_selected 置顶） |
| 6 | 采纳意见立即生效并高亮 | 「采纳并修复」→ 修复生成新版本 → 右侧文档对应块朱红闪示定位；不可自动修复的「标记待改」并定位 |
| 7 | 水印图暂可用 | 选图与编辑器图片选择器不再排除水印图，仅保留「水印」徽标 |
| 8 | 卡片要有设计感 | 主题重写为「编辑部快报」：封面整版墨色域+朱红 kicker+关键词 chips+日期+页数；内容页纸面+节号徽章+页脚细线品牌行；零渐变零阴影；封面标题 4 行内自适应缩字号；正文引用标记 `[^mat_*]` 一律剥离入结构字段 |

**顺手修掉的真实 bug**（真实全链路暴露）：FTS5 MATCH 标点语法错误（短语化+LIKE 兜底）；任务失败重试被「过期任务保护」误杀（准入含自身进行态+同态迁移幂等）；定稿后复审拽回编辑态的竞态（软审：只出报告不动状态）；队列 payload_json 未解析导致发布平台被默认覆盖。

## 第三阶段修订（2026-10-25 用户反馈 5 大块，全部落地）

| # | 反馈 | 落实 |
|---|---|---|
| 一 | 「洗稿 Agent」→「创作 Agent」 | 全局改名：`app/agents/creator.py`、`config/prompts/creator/`、阶段键 `create`、状态 `CREATING`、路由用途 `create`、UI/文档全部新表述；品牌文案同步去「洗稿」 |
| 二 | `resource/` 统一素材&产出目录 | data→resource 迁移（含迁移脚本重构存量项目文件夹）；gitignore；项目文件夹 = `输入标题-日期时间`，创作定题后自动改名为 `拟定标题-日期时间`（日期保留）；`reference/` 内输入文章与搜索文章同级、每篇一个标题子文件夹；类型子目录 图片/视频/音频/其他；产出 drafts/exports 并入项目文件夹 |
| 三 | 收集 Agent 能力优化 | 手动加链接（单/批量 `ingest` 任务）、单链重抓 recrawl；多类型爬取（公众号视频 iframe/mpvideo + 音频 mpvoice + 通用站视频标签）；纯规则过滤（文本垃圾行/推荐区尾巴、图片 URL 黑名单+尺寸/比例/大小、pHash 近似去重，不调 LLM）；相关性守卫（结果须命中关键词/实体） |
| 四 | 素材库 GUI 规范 | 两大顶层库 + 4 分栏（文章/图片/视频/其他）；图片视频按来源文章分组；拖拽复制公共库→本文库；勾选「导入 & 创作」传集合给创作 Agent 并跳创作页；标题看 markdown 原文、链接开源网址、灯箱大图、视频弹窗播放（链接型外跳）、「其他」点击打开所在文件夹 |
| 五 | 爬虫升级 + tools/ 独立工具 | Bing 零配置搜索器（/ck/a 跳转 base64 还原，mkt=zh-CN）接入 tavily→bing→ddg→arxiv 链；wxv_ 视频号降级「链接+封面」素材；`tools/scraper/` 独立工具：CLI + 独立 GUI 服务（127.0.0.1:8765）+ 单文件界面，复用爬虫与过滤规则、不连库 |

**已知边界**：wxv_ 视频号取流在纯服务端不可稳定实现（需本机微信会话换凭证，如 wechatDownload 方案，列为后续候选）；免费搜索端点（DDG/Bing）存在反爬波动，链式兜底+相关性守卫已尽量消化，追求稳定可配 TAVILY_API_KEY。
