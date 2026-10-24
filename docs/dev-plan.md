# 开发计划（M1 · 本地 MVP）

> 依据 `docs/design/` 与 2026-10-24 拍板结论制定。目标：PC 本地可用的完整闭环——录入链接 → 收集 → 洗稿 → 审稿 → 人工编辑定稿 → 导出多平台发布包。

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
