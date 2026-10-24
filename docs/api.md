# 接口文档（M1）

Base URL: `http://127.0.0.1:8000`。所有接口前缀 `/api`。运行时亦可在 `/docs` 查看自动生成的 OpenAPI。

**鉴权**：`.env` 设置 `APP_ACCESS_TOKEN` 后，所有请求需带 `?token=...` 或 `Authorization: Bearer ...`（本机未设置则免鉴权）。

**静态资源**：`/files/...` 映射 `data/` 目录（素材图片、导出包）；`GET /api/materials/{mid}/file` 按素材 id 直接取文件。

## 文章 Articles

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/articles` | 录入链接。Body: `{url, user_notes?, style_pack?, target_word_count?, auto_collect=true}`。默认自动入队收集任务 |
| GET | `/api/articles?status=&q=` | 列表。`status` ∈ `New/Process/Done`；`q` 搜标题/链接。返回含 `ui_status`、`progress` |
| GET | `/api/articles/{aid}` | 详情（状态、素材数、版本列表、最新审稿、发布记录） |
| POST | `/api/articles/{aid}/advance` | 推进阶段。Body: `{stage: collect\|rewrite\|review}`。状态不允许时 409 |
| POST | `/api/articles/{aid}/finalize` | 定稿。Body: `{force=false}`；存在未处理 blocker 时 409，`force=true` 强制定稿并留痕 |
| POST | `/api/articles/{aid}/reopen` | 定稿后回炉编辑（FINALIZED/DONE → EDITING） |

## 素材 Materials

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/articles/{aid}/materials?scope=article&kind=` | 文章素材组 |
| GET | `/api/materials/common?kind=` | 公共素材库 |
| POST | `/api/articles/{aid}/materials/upload` | multipart 上传（`file` 字段） |
| POST | `/api/materials/upload` | 上传到公共库 |
| POST | `/api/articles/{aid}/materials/url` | `{url, ref_type?}` 爬取网址入库（正文+图片） |
| POST | `/api/articles/{aid}/materials/scan-inbox` · `/api/materials/scan-inbox` | 摄取 inbox/ 手动拷入的文件 |
| DELETE | `/api/materials/{mid}` | 删除素材（行+索引+文件） |
| GET | `/api/materials/{mid}/text` | 取文本素材正文 |

## 文案 Drafts（块模型，一切修改产生新版本）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/articles/{aid}/draft?version=` | 取文案（默认最新版）+ 版本列表 |
| GET | `/api/articles/{aid}/versions` | 版本列表 |
| PUT | `/api/drafts/{draft_id}/edit` | 批量编辑。Body: `{ops: [{op, block_id, ...}]}`，op ∈ `update`(text) / `remove` / `replace_image`(asset_id) / `set_caption`(caption) / `update_meta`(field ∈ one_liner/keywords/title_candidates/title_selected)。落盘新版本；改动超阈值自动触发复审 |
| POST | `/api/drafts/{draft_id}/regenerate` | 段落 AI 重生成。`{block_ids: [], instruction}` → 新版本 |
| POST | `/api/drafts/{draft_id}/insert-refs` | 参考素材融合插入。`{material_ids: [], after_block_id?, instruction?}` → 新版本 |

## 审稿 Reviews

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/articles/{aid}/reviews/latest` | 最新审稿报告 + checklist（按 severity 排序） |
| POST | `/api/review-items/{item_id}/resolve` | 处理条目。`{action: accept\|dismiss\|fix, note?}`；`fix` 立即对该块 AI 修复并生成新版本（前端「采纳并修复」，成功后对应块高亮闪示）；`accept` 为标记待改并定位段落。定稿/发布态下的复审为「软审」：只出报告不动文章状态 |

审稿六维：`layout`（规则）、`fact`/`attribution`/`compliance`/`ai_flavor`（LLM）、`originality`（SimHash/向量）。

## 发布（一阶段：统一导出包）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/articles/{aid}/publish` | `{platforms: [wechat_mp,xhs,weibo,x]}` 入队导出任务（须先定稿） |
| GET | `/api/articles/{aid}/publish-jobs` | 导出结果（目录、文件清单、消息） |
| GET | `/api/articles/{aid}/exports` | 导出目录文件列表 |
| POST | `/api/articles/{aid}/cards?theme=` | 单独生成小红书卡片 PNG（Playwright 截图） |

## 设置 / 系统

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/settings` | 生效配置 + 渠道配置状态 + LLM/搜索/embedding 可用性 |
| PUT | `/api/settings` | `{key: "a.b.c", value}` 写 DB 覆盖层（`llm.channels` 仅可改 yaml） |
| GET | `/api/jobs?article_id=` | 任务队列状态 |
| GET | `/api/sse` | 事件流（status.changed / *.finished / job.failed 等） |
| GET | `/api/health` | 健康检查（免鉴权） |

## 错误约定

- `400` 参数错误 · `404` 资源不存在 · `409` 状态冲突（含 blocker 禁止定稿） · `502` 外部调用失败（爬取/LLM） · `503` 所需渠道未配置
- 错误体统一 `{ "detail": "人类可读信息" }`
