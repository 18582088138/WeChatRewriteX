# 开发进度交接（PROGRESS.md）

> **给下一次会话**：这份文档 + `docs/design/` 设计文档 + git log 即可恢复全部上下文。
> 读法：先看本文件「当前状态」与「下一轮该做什么」，细节查设计文档对应章节。

## 当前状态（截至 2026-10-25）

**功能完整可用、本地运行中的 M1+ 产品**。三轮主迭代 + 四轮修订全部落地，
测试 26 项全绿，git main 分支 10 次提交（未推 GitHub：本机无 gh CLI，远端未配）。

- 启动：conda `xkd_env_py312`（Python 3.12.14）→ `python -m app` → http://127.0.0.1:8000
- 前端已构建于 `web/dist/`（改前端后需 `cd web && npm run build`）
- 数据根 `resource/`（gitignore），日志 `log/`（gitignore，开发者模式才写）

## 产品是什么

AI 行业要闻「收集 → 创作 → 审稿 → 人工定稿 → 多平台发布包导出」的本地助手。
输入一篇文章链接，三个 Agent（收集/创作/审稿）流水线处理，人工在工作台审阅编辑，
定稿后导出公众号/小红书（分页卡片组图）/微博/X 的发布包（手动发布；自动推送是二阶段）。

## 已验证能跑通的真实链路

- 收集：公众号正文+图片抓取、DuckDuckGo/Bing 零配置扩搜、arXiv 论文、Pexels/Pixabay
  媒体补充、纯规则过滤（文本垃圾/低质图/pHash 去重）、mpvideo.qpic.cn 签名直链视频实体下载
  （Vidu 文章实测 21 图 + 4 视频实体落盘）
- 创作：DeepSeek 成稿（风格包 tech-evangelist 人设），勾选素材集合创作、段落级 AI 重写、
  资料融合插入、必配图兜底、小红书分页
- 审稿：六维 checklist（排版规则/禁用词/SimHash 撞重阈值 blocker/LLM 事实来源合规 AI 味），
  采纳即修复 + 高亮，blocker 禁定稿可强制留痕
- 编辑：Notebook 工作台（双击编辑/点外保存/增删块/拖素材入位/标题副标题置顶/图注编辑），
  块级增量版本 + 主动保存版本（备注）+ 一键回滚
- 发布：四平台导出包（公众号 HTML 可复制进编辑器 / 小红书卡片 PNG / 微博短文 / X 推文串）

## 架构速查（勿推翻）

| 层 | 位置 | 要点 |
|---|---|---|
| 领域模型 | `app/core/models.py` | **DraftDoc 块模型**（稳定 id 块列表）是编辑/审稿/分页/导出的地基 |
| 版本 | `app/services/draft_service.py` + `app/storage/dao.py` | 块级增量：`draft_changes` 差异日志 + `drafts` 稀疏 checkpoint；HEAD=checkpoint+重放；**主动保存版本**（origin=manual+note）才进回滚列表 |
| 状态机 | `app/core/statemachine.py` | NEW→COLLECTING→…→DONE/FAILED；定稿后复审为软审（不动状态） |
| 队列 | `app/pipeline/queue.py` | 双泳道线程（collect/ingest/deepsearch ∥ create/review/publish），`UPDATE...RETURNING` 原子认领，崩溃恢复 |
| LLM | `app/services/llm/router.py` | OpenAI 兼容薄路由（deepseek/ark/openrouter 优先级+fallback+schema 校验重试+成本日志）；key 在 `.env` |
| 检索 | `app/services/rag/index.py` | FTS5 trigram（短语化+LIKE 兜底）+ embedding API 可选（无 key 降级纯 FTS） |
| 爬虫 | `app/services/crawl/` | wechat_mp（自写 #js_content 解析+视频音频提取）/ trafilatura / arxiv / fixture；插件 registry |
| 搜索 | `app/services/search/` | tavily→bing→duckduckgo→arxiv；Bing 需解 /ck/a 跳转 base64 |
| 媒体 | `app/services/media/` | 下载（防盗链 Referer）、filter.py 纯规则过滤、stock.py 图库补充、video_dl.py（yt-dlp） |
| 主题提取 | `app/services/textmine.py` | **纯规则禁 LLM**：标题分句×3+型号 token+引号词+实体词典+高分核心句 |
| 卡片 | `app/services/cards/render.py` + `themes/tech-note/` | HTML 模板→Playwright 截图 1080×1440，浏览器内分页+溢出校验；「编辑部快报」平面风 |
| 配置 | `config/` | prompts/（Jinja2 按 Agent 分目录）、styles/tech-evangelist/（风格包）、settings.yaml；DB settings 覆盖层优先级最高 |
| 前端 | `web/src/` | Vue3+NaiveUI+Tailwind；views: ArticleList/Workbench/Settings；components: MaterialsPanel/BlockEditor/ReviewPanel/PublishPanel/StatusChip |
| 独立工具 | `tools/scraper/` | CLI + GUI 服务（127.0.0.1:8765），复用爬虫与过滤规则，不连库 |

## 数据布局（resource/，唯一数据根，gitignore）

```
resource/
├── app.db(.shm/.wal)     # SQLite：文章/素材索引/版本/审稿/任务/成本
├── style_reference/      # 13 篇范文（风格蒸馏参照）
├── common/               # 公共素材库：图片/视频/音频/其他/ + inbox（无 reference）
└── <标题-YYYYMMDD-HHmm>/  # 项目文件夹（创作定题后自动改名为拟定标题）
    ├── reference/<文章标题>/{page.html,content.md,meta.json,图片/,视频/,音频/,其他/}
    ├── inbox/  drafts/   # drafts: vNNN checkpoint + runs/ Agent 运行记录
    ├── exports/<平台>/   # 发布包（含 xhs_cards/ 卡片）
    └── notes.md          # 收集报告
```

素材统一命名 `NNN-类型-来源标题前5~8字.ext`；`materials.path` 相对 resource/；
`articles.lib_dir` 记录项目文件夹名；`articles.selected_json` 存创作会话勾选。
**文件不能在资源管理器手动移动**（DB 路径会失效），要走应用内操作。

## 关键设计决策（拍板记录）

1. 发布一阶段只做导出包手动发布；API/RPA 自动推送归后续阶段。
2. 风格 = 「轻松诙谐但严谨科学的技术传火人」人设（14 篇范文蒸馏，规则见 `config/styles/tech-evangelist/` 与 `docs/design/06-style-guide.md`）。
3. 审稿撞重双保险：创作侧 prompt 预防 + 审稿 SimHash/Jaccard 双阈值 blocker。
4. 水印图当前可用仅打标（后续再处理）。
5. LLM 与搜索均可降级运行（无 key 走保底稿/仅原文/纯 FTS），测试全程离线可跑。
6. GUI 遵循 taste-skill app-screen 规范（已装 `~/.zcode/skills/taste-skill`）：1px 边线无阴影、近黑主按钮、朱红 #C63B24 accent 克制、无渐变无 emoji。

## 踩过的坑（别再踩）

- **FTS5 MATCH** 遇标点语法错误 → 短语化包裹 + LIKE 兜底（dao.search_materials_fts）。
- **任务重试**：阶段准入必须含自身进行态 + 同态迁移幂等，否则重试被防呆误杀。
- **mpvideo.qpic.cn 直链**：藏在文章 inline JS，`&` 转义为 `\x26amp;` 必须先反转义再匹配，
  否则截断丢签名必 403（`services/crawl/wechat_video.py`）；readtemplate 条目在有直链时跳过防重。
- **草稿不存在 bug**：增量版本后前端持有的 `<aid>-vN` 不是实体行，`resolve_head_row` 回退 HEAD。
- **拖拽 500**：copy 端点 INSERT 列数与占位符必须逐个数齐（18↔18）。
- **sha 去重**：复制会合法产生同 sha 多行，去重必须查全部再按 scope 过滤。
- **grid 自动放置**：fixed 定位的标记元素也是 grid 子项，会挤扁中央列——显式 grid-column。
- **heredoc 转义**：`\\x26`、三引号 docstring、`\n` 在 Bash heredoc 里会被吃——复杂补丁写成临时 .py 文件执行。

## 已知边界 / 待办候选

- 懒加载 wxv_ 视频号无直链 → 链接型素材（iframe 弹窗 + 外跳兜底）；要实体需本机微信凭证方案。
- 免费搜索端点（Bing/DDG）有反爬波动；稳定可配 TAVILY_API_KEY。
- embedding 语义检索/撞重需要 OpenAI 兼容 embedding key（如火山方舟 doubao-embedding），未配则纯 FTS。
- 卡片只有 1 套主题；移动端 PWA 打磨未做；移动端轻编辑是二阶段。
- 创作聚焦受勾选素材影响大（混主题会偏题）——这是特性不是 bug。
- M2 候选：公众号 API/RPA 推送、watchdog 素材监听、成本看板页、多卡片主题、字符级 diff。

## 下一轮怎么接

1. 本目录说「继续」即可——项目记忆 + 本文档 + git log 提供全部上下文。
2. 若要继续优化：优先用 3~5 篇真实选题完整走全流程，把风格包与审稿阈值用真实案例校准。
3. 若要推 GitHub：先装/配 gh CLI，再 `gh repo create` 推送（`.env`/`resource/`/`log/` 已在 gitignore）。
4. 若要二阶段发布：读 `docs/design/05-publishing.md` 的 Publisher 插件接口与降级链。
