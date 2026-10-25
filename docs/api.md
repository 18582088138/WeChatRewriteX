# 接口文档（M1 · 2026-10-25 与代码核对同步）

Base URL: `http://127.0.0.1:8000`，所有接口前缀 `/api`。运行时可访问 `/docs` 查看自动生成的 OpenAPI。

**鉴权**：`.env` 设置 `APP_ACCESS_TOKEN` 后，除 `/api/health` 外所有请求需带 `?token=...` 或
`Authorization: Bearer ...`（未设置则免鉴权，仅限本机）。

**静态资源**：`/files/...` 映射 `data/` 目录（素材、发布包、卡片）；
`GET /api/materials/{mid}/file` 按素材 id 直接取文件（编辑器图片块用）。

**约定**：

- 错误体统一 `{ "detail": "人类可读信息" }`；状态码 `400` 参数错误 · `404` 不存在 ·
  `409` 状态冲突 · `502` 外部调用失败（爬取/LLM） · `503` 所需渠道未配置。
- 文案的**一切修改产生新版本**（`origin` ∈ agent / human / auto_fix / insert_refs），
  改动超阈值（默认 ≥3 块或字数变化 >20%）自动触发增量复审。
- 文章状态机与 UI 三态（New/Process/Done）映射见 `docs/design/02`；定稿/发布态下的复审为
  **软审**（只出报告，不改文章状态）。
- LLM/搜索/embedding 未配置时走降级路径（保底稿 / 仅原文 / 纯 FTS），流程不中断。

## 文章 Articles

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/articles` | 录入链接。`{url, user_notes?, style_pack?, target_word_count?, auto_collect=true}`，默认自动入队收集 |
| GET | `/api/articles?status=&q=` | 列表。`status` ∈ `New/Process/Done`；返回含 `ui_status`、`progress`（运行/排队阶段） |
| GET | `/api/articles/{aid}` | 详情：状态、素材数、版本列表、最新审稿、发布记录 |
| POST | `/api/articles/{aid}/advance` | 推进阶段 `{stage: collect\|create\|review, selected_material_ids?}`；当前状态不允许 → 409。`selected_material_ids` 为 create 阶段的「勾选参与创作素材集」（素材库「导入 & 创作」按钮）；收集 → 后续阶段需手动或 `pipeline.auto` 连跑 |
| POST | `/api/articles/{aid}/finalize` | 定稿 `{force=false}`；存在未处理 blocker 时 409，`force=true` 强制定稿并留痕（返回 `forced_blockers`） |
| POST | `/api/articles/{aid}/reopen` | 定稿/完成后回炉编辑（FINALIZED/DONE → EDITING） |
| POST | `/api/articles/{aid}/deepsearch` | 深度搜索：基于已提取主题的新一轮检索，仅增量补充 reference（须先完成收集；入队 `deepsearch` 任务） |
| GET | `/api/jobs?article_id=&limit=` | 任务队列状态（type/status/attempts/error/结果） |

## 素材 Materials

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/articles/{aid}/materials?scope=article&kind=` | 文章素材组（kind ∈ text/image/video/doc/link） |
| GET | `/api/materials/common?kind=` | 公共素材库 |
| POST | `/api/articles/{aid}/materials/upload` | multipart 上传（`file` 字段）；sha256 全局去重 |
| POST | `/api/materials/upload` | 上传到公共库 |
| POST | `/api/articles/{aid}/materials/url` | `{url, ref_type?}` 爬取网址入库（正文+图/视频/音频） |
| POST | `/api/articles/{aid}/materials/batch-url` | `{urls: [], ref_type?}` 批量链接批量抓取（入队 `ingest` 任务，逐链接记录成败） |
| POST | `/api/materials/{mid}/recrawl` | 单链接独立重抓：更新正文标题并补充媒体 |
| POST | `/api/materials/{mid}/copy-to-article` | `{article_id}` 公共库素材复制到本文素材库（同文件新行，不占盘；GUI 拖拽即调用此接口） |
| POST | `/api/materials/{mid}/copy-to-common` | 本文素材反向复制到公共库（sha256 校验，公共库已有同文件则跳过） |
| PATCH | `/api/materials/{mid}` | `{title?, note?}` 改素材标题/备注 |
| POST | `/api/materials/{mid}/reveal` | 在系统文件管理器中打开素材所在文件夹 |
| POST | `/api/articles/{aid}/materials/scan-inbox` · `/api/materials/scan-inbox` | 摄取对应 inbox/ 里手动拷入的文件 |
| GET | `/api/materials/{mid}/file` | 直接返回素材文件内容（图片/视频预览） |
| GET | `/api/materials/{mid}/text` | 取文本素材正文 |
| DELETE | `/api/materials/{mid}` | 删除素材（行 + FTS/向量索引 + 文件） |

**视频素材的两种形态**：`path` 非空 = 已下载的本地文件（弹窗内 `<video>` 播放；公众号
mpvideo.qpic.cn 签名直链已可实体下载）；`path` 为空但 `source_url` 非空 = 链接型视频
（懒加载 wxv_，弹窗内 iframe 播放器 + 外跳兜底；封面已下载为图片素材可作配图）。

**进度事件**：`stage.progress`（分阶段文字日志：抓取/提取/检索/爬取/下载/入库），
SSE 推送，前端工作台实时展示。主题与报道主体提取为**纯规则**（services/textmine.py，
不调 LLM）。

## 文案 Drafts（块模型）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/articles/{aid}/draft?version=` | 取文案（默认最新版）+ 版本列表；`draft.doc` 为块模型 |
| GET | `/api/articles/{aid}/versions` | 版本列表（version/origin/word_count/status） |
| PUT | `/api/drafts/{draft_id}/edit` | 批量编辑 `{ops: [...]}`。op ∈ `update`(block_id+text) / `remove` / `replace_image`(asset_id) / `set_caption` / `update_meta`(field ∈ `title_selected` `title_candidates` `one_liner` `keywords`)。返回 `{version, recheck_enqueued}` |
| POST | `/api/drafts/{draft_id}/regenerate` | 段落 AI 重生成 `{block_ids: [], instruction}` → 新版本；LLM 未配置 → 503 |
| POST | `/api/drafts/{draft_id}/insert-refs` | 参考素材融合插入 `{material_ids: [], after_block_id?, instruction?}` → 新版本 |

## 审稿 Reviews

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/articles/{aid}/reviews/latest` | 最新审稿报告 + checklist（按 severity 排序：blocker → warn → info） |
| POST | `/api/review-items/{item_id}/resolve` | `{action: fix\|accept\|dismiss, note?}`。`fix`=采纳并修复（该块 AI 重写生成新版本，要求 `auto_fixable` 且有 `block_id`）；`accept`=标记待改（人工跟进）；`dismiss`=忽略（可留理由） |

六维：`layout`（规则）、`compliance`（禁用词表+LLM）、`originality`（SimHash/Jaccard 双阈值）、
`fact`/`attribution`/`ai_flavor`（LLM + 素材取证）。`scores_json` 示例：
`{"originality_max_jaccard": 0.07, "layout_issues": 0, "ai_flavor": 2}`。

## 发布（一阶段：统一导出发布包）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/articles/{aid}/publish` | `{platforms: [wechat_mp,xhs,weibo,x]}` 入队导出任务；须 FINALIZED/DONE，否则 409 |
| GET | `/api/articles/{aid}/publish-jobs` | 各平台导出结果（`export_dir`、文件清单、消息） |
| GET | `/api/articles/{aid}/exports` | 文章文件夹 `exports/` 下的文件列表（含 `lib_dir` 绝对路径） |
| POST | `/api/articles/{aid}/cards?theme=` | 单独生成小红书卡片 PNG（Playwright 截图，含溢出校验） |

导出位置：`data/library/articles/<标题_短id>/exports/<平台>/`，各含 README.txt 发布说明；
小红书卡片在 `exports/xhs/cards/`（页页 1080×1440 PNG）。

## 设置 / 系统

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/settings` | 生效配置 + 渠道配置状态（不返回密钥）+ LLM/搜索/embedding 可用性 |
| PUT | `/api/settings` | `{key: "a.b.c", value}` 写 DB 覆盖层（优先级最高；`llm.channels` 仅可改 yaml） |
| GET | `/api/sse` | 事件流。事件：`status.changed` `job.enqueued` `job.failed` `collect.finished` `create.finished` `review.finished` `draft.saved` `draft.finalized` `publish.finished` `material.ingested` |
| GET | `/api/health` | 健康检查（免鉴权） |
