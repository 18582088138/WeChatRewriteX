# 接口文档（1.11.0 · 2026-10-28）

Base URL: `http://127.0.0.1:8000`，所有接口前缀 `/api`。运行时可访问 `/docs` 查看自动生成的 OpenAPI。

**鉴权**：设置 `APP_ACCESS_TOKEN` 后，业务接口使用 `Authorization: Bearer ...`。
`GET /api/session` 验证令牌并签发 HttpOnly、SameSite 会话，供 SSE 和媒体请求使用。
查询参数 `?token=...` 不再接受；`/api/health` 免鉴权。未设置令牌时仅允许本机访问，远程绑定必须配置令牌。

**静态资源**：`/files/...` 仅提供已登记素材、完成的发布包和限定卡片，禁止数据库、锁和 staging；
`GET /api/materials/{mid}/file` 按素材 id 直接取文件（编辑器图片块用）。

**约定**：

- 错误体统一 `{ "detail": "人类可读信息" }`；状态码 `400` 参数错误 · `404` 不存在 ·
  `409` 状态/版本冲突 · `422` 类型或范围校验失败 · `502` 外部调用失败（爬取/LLM） · `503` 所需渠道未配置或服务未就绪。
- 文案版本为**块级增量 + checkpoint**：每次实际编辑原子记录变更组，版本时间线保留历史；
  创建、主动保存、定稿和回滚生成 checkpoint。旧 draft ID 提交返回 409，虚构版本返回 404；
  定稿、保存版本和回滚可提交 `expected_version` 防止覆盖并发编辑。
  改动超阈值（默认 ≥3 块或字数变化 >20%）自动触发增量复审。
- 文章状态机与 UI 三态（New/Process/Done）映射见 `docs/design/02`；定稿/发布态下的复审为
  **软审**（只出报告，不改文章状态）。
- LLM/搜索/embedding 未配置时走降级路径（保底稿 / 仅原文 / 纯 FTS），流程不中断。

## 文章 Articles

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/articles` | 资料收集录入。`{url?, title?, user_notes?, style_pack?, target_word_count?, auto_collect=true}`。链接模式：url 必填、默认自动入队收集；本地文件模式：url 留空 + title 主题名（立档为 `local://` 文章，不自动收集，素材走批量上传） |
| GET | `/api/articles?status=&q=&limit=&offset=` | SQL 分页列表。`status` ∈ `New/Process/Done/Failed`；limit 默认 200，最大 500。返回文章、状态计数、总数、分页参数及批量 progress |
| GET | `/api/articles/{aid}` | 详情：状态、素材数、版本列表、最新审稿、发布记录 |
| POST | `/api/articles/{aid}/advance` | 推进阶段 `{stage: collect\|create\|review, selected_material_ids?}`；当前状态不允许 → 409。`selected_material_ids` 为 create 阶段的「勾选参与创作素材集」（素材库「导入 & 创作」按钮）；收集 → 后续阶段需手动或 `pipeline.auto` 连跑 |
| POST | `/api/articles/{aid}/finalize` | `{force=false, expected_version?}` 生成正式 checkpoint。审稿必须匹配当前内容；缺失、过期、AI 失败或未处理 blocker 返回 409，force=true 跳过审稿限制并记录原因，仍不能跳过版本冲突。规则降级审稿允许人工定稿。已定稿幂等，之后实际编辑或回滚转回 EDITING |
| POST | `/api/articles/{aid}/reopen` | 定稿/完成后回炉编辑（FINALIZED/DONE → EDITING） |
| POST | `/api/articles/{aid}/deepsearch` | 深度搜索：基于已提取主题的新一轮检索，仅增量补充 reference（须先完成收集；入队 `deepsearch` 任务） |
| GET | `/api/jobs?article_id=&limit=` | 任务队列状态（type/status/attempts/error/结果） |

## 素材 Materials

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/articles/{aid}/materials?scope=article&kind=` | 文章素材组（kind ∈ text/image/video/doc/link） |
| GET | `/api/materials/common?kind=` | 公共素材库 |
| POST | `/api/articles/{aid}/materials/upload` | multipart 上传（`file` 字段）；同归属按 sha256 去重，上传受大小和数量限制 |
| POST | `/api/articles/{aid}/materials/upload-batch` | 批量上传（`files` 多文件，本地文件/文件夹收集）。自动识别类型分流：md/txt→文章，html/pdf 抽取正文→文章，图片/视频/音频按扩展名，其余→其他；返回 `{ok:[], failed:[], total}` 逐条成败。local:// 文章上传成功即转 COLLECTED |
| POST | `/api/materials/upload` | 上传到公共库 |
| POST | `/api/articles/{aid}/materials/url` | `{url, ref_type?}` 爬取网址入库（正文+图/视频/音频） |
| POST | `/api/articles/{aid}/materials/batch-url` | `{urls: [], ref_type?}` 批量链接批量抓取（入队 `ingest` 任务，逐链接记录成败） |
| POST | `/api/materials/{mid}/recrawl` | 重抓生成新素材并归档旧行；已有引用继续保留旧来源 |
| POST | `/api/materials/{mid}/copy-to-article` | `{article_id}` 公共库素材复制到本文素材库（同文件新行，不占盘；GUI 拖拽即调用此接口） |
| POST | `/api/materials/{mid}/copy-to-common` | 本文素材反向复制到公共库（sha256 校验，公共库已有同文件则跳过） |
| PATCH | `/api/materials/{mid}` | `{title?, note?}` 改素材标题/备注 |
| POST | `/api/materials/{mid}/reveal` | 在系统文件管理器中打开素材所在文件夹 |
| POST | `/api/articles/{aid}/materials/scan-inbox` · `/api/materials/scan-inbox` | 摄取对应 inbox/ 里手动拷入的文件 |
| GET | `/api/materials/{mid}/file` | 直接返回素材文件内容（图片/视频预览） |
| GET | `/api/materials/{mid}/text` | 取文本素材正文 |
| DELETE | `/api/materials/{mid}` | 归档素材并移出活动列表/FTS/向量检索，保留行、文件和历史引用 |

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
| GET | `/api/articles/{aid}/versions` | 版本时间线（checkpoint 快照 + 编辑变更组） |
| POST | `/api/articles/{aid}/versions/save` | `{note?, expected_version?}` 当前 HEAD 落为命名 checkpoint |
| POST | `/api/articles/{aid}/rollback` | `{version, expected_version?}` 重建目标态存为新 checkpoint；旧 HEAD 返回 409，目标不存在返回 404 |
| PUT | `/api/articles/{aid}/selection` | `{material_ids: []}` 保存创作会话勾选素材集合（左窗数据源） |
| PUT | `/api/drafts/{draft_id}/edit` | 批量编辑 `{ops: [...]}`。op ∈ `update` / `remove` / `replace_image` / `set_caption` / `insert_after`（新增块/插图） / `update_meta`。返回 `{version, recheck_enqueued, folder_renamed}`；`title_selected` 触发标题联动（正文一级标题+项目文件夹改名） |
| POST | `/api/drafts/{draft_id}/regenerate` | 段落 AI 重生成 `{block_ids: [], instruction}` → 新版本；LLM 未配置 → 503 |
| POST | `/api/drafts/{draft_id}/insert-refs` | 参考素材融合插入 `{material_ids: [], after_block_id?, instruction?}` → 新版本 |

## 审稿 Reviews

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/articles/{aid}/reviews/latest` | 最新报告、checklist、current（内容是否匹配）及 coverage（full/rules_only/failed）；迟到报告不推进新稿或已定稿状态 |
| POST | `/api/review-items/{item_id}/resolve` | `{action: fix\|accept\|dismiss, note?}`。`fix`=采纳并修复（该块 AI 重写生成新版本，要求 `auto_fixable` 且有 `block_id`）；`accept`=标记待改（人工跟进）；`dismiss`=忽略（可留理由） |

六维：`layout`（规则）、`compliance`（禁用词表+LLM）、`originality`（SimHash/Jaccard 双阈值）、
`fact`/`attribution`/`ai_flavor`（LLM + 素材取证）。`scores_json` 示例：
`{"originality_max_jaccard": 0.07, "layout_issues": 0, "ai_flavor": 2}`。

## 发布（一阶段：统一导出发布包）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/articles/{aid}/publish` | `{platforms: [wechat_mp,xhs,weibo,x]}` 当前稿须定稿；入队绑定定稿 ID、素材清单和配置快照。结果区分 SUCCESS/PARTIAL_FAILED/FAILED |
| POST | `/api/articles/{aid}/publish/retry` | `{platform?}` 只重试尚未被后续成功/在途任务覆盖的失败平台，沿用原定稿、素材和配置。重复单平台点击复用在途任务 |
| GET | `/api/articles/{aid}/publish-jobs` | 各平台导出结果（`export_dir`、文件清单、消息） |
| GET | `/api/articles/{aid}/exports` | 各平台最新完成发布包与卡片文件，排除失败 staging，含 lib_dir |
| POST | `/api/articles/{aid}/exports/reveal` | `{platform}` 打开该平台最新完成发布包的本地文件夹；未生成 404 |
| POST | `/api/articles/{aid}/cards?theme=` | 单独生成小红书卡片 PNG（Playwright 截图，含溢出校验） |

导出位置：`<data_root>/library/articles/<文章目录>/exports/runs/<job-id>/<平台>/`。
各含 README.txt、snapshot.json 和带文件 hash 的 manifest.json；小红书 cards/ 为 1080×1440 PNG。

## 设置 / 系统

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/settings` | 生效配置 + 渠道配置状态（不返回密钥）+ LLM/搜索/embedding 可用性 |
| PUT | `/api/settings` | `{key: "a.b.c", value}` 仅允许有类型/范围校验的动态项；数据根、渠道、hooks 等需停机编辑配置并重启 |
| GET | `/api/session` | 验证访问令牌并签发 SSE/媒体会话 Cookie |
| GET | `/api/sse` | 事件流。事件：`status.changed` `job.enqueued` `job.failed` `collect.finished` `create.finished` `review.finished` `draft.saved` `draft.finalized` `publish.finished` `material.ingested` |
| GET | `/api/health` | 健康检查（免鉴权） |
| GET | `/api/ready` | 检查数据库与 worker，返回队列、磁盘及事件序号/丢弃指标，未就绪为 503 |
| GET | `/api/logs/tail?lines=` | 运行日志尾部（须开启开发者模式，否则 403） |
| GET | `/api/articles/{aid}/costs` | API 费用监控：按 收集/创作/审稿 环节聚合调用数与 tokens + 全流程汇总 |
