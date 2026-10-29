> V1.15 当前实现以 [版本、导出与平台说明](../release/V1.15.md) 和 [架构契约](../ARCHITECTURE.md) 为准。下文早期设计/开发记录中的逐次编辑版本、导出批次及尾页约定已由 V1.15 替代。

# 03 · 数据模型与素材库

## 存储原则

- **SQLite 管索引与状态，文件系统管内容**。图片/视频/快照/文案都是文件，DB 只存路径、哈希与元数据——素材可直接拷进文件夹被识别，也方便用户用系统查看器浏览。
- 一切内容带哈希与来源，可追溯、可去重。

## SQLite 表（核心）

```sql
articles(                              -- 任务
  id, url, title, source_site, published_at,
  status,                -- 状态机, 见 02
  style_pack, target_word_count, user_notes,
  lib_dir,                 -- 素材文件夹名 (标题_短id, 标题后到自动迁移)
  created_at, updated_at)

materials(                             -- 素材 (文章组与公共库统一一张表)
  id, scope,               -- 'article' | 'common'
  article_id,              -- scope=article 时归属
  kind,                    -- text | image | video | doc | link
  path,                    -- 库内相对路径
  sha256, phash,           -- 去重
  source_url, source_material_id,      -- 出处 (取自哪篇参考)
  watermark,               -- 0/1/NULL(未检测)
  width, height, duration,
  ref_type,                -- primary(原文) | reference | foundational
  fetch_status, note, meta_json,
  created_at)

material_texts(material_id, content)    -- 文本素材正文 (入库即进 FTS 索引)
material_fts                            -- FTS5 trigram 虚表 (SQLite 不支持时降级 LIKE)
embeddings(material_id, dim, vector)    -- 向量索引 (float32 blob; 无 embedding 渠道时为空表)

drafts(                                -- 文案版本链
  id, article_id, version,             -- version 单调递增
  doc_json,                -- 文档块模型, 见下
  keywords_json, one_liner, title_candidates_json,
  word_count, status,      -- editing | finalized
  parent_version,          -- 由哪版派生 (重生成/编辑)
  origin,                  -- agent | human | auto_fix | insert_refs
  created_at)

reviews(
  id, article_id, draft_id, draft_version,
  scores_json,             -- 六维得分
  created_at)

review_items(                          -- checklist
  id, review_id, category, severity, block_id,
  message, suggestion, evidence_json, auto_fixable,
  status,                  -- pending|accepted|dismissed|fixed
  resolved_by, resolved_note)

publish_targets(                       -- 平台账号配置 (非密钥)
  id, platform,            -- wechat_mp | x | xhs | weibo
  account_label, mode,     -- api | rpa | export
  capabilities_json, enabled, config_json)

publish_jobs(
  id, article_id, draft_id, target_id,
  variant_json,            -- 平台适配后的内容快照
  status, result_json, remote_ref,     -- 草稿 id / 草稿箱链接
  created_at)

jobs(                                  -- 任务队列
  id, type, payload_json, status, attempts, run_after,
  result_json, created_at, updated_at)

llm_calls(                             -- 成本审计
  id, article_id, stage, channel, model,
  prompt_tokens, completion_tokens, latency_ms, cost_est, created_at)

settings(key, value_json)              -- UI 可改配置, 覆盖 config/settings.yaml

-- prompt 模板不进库: 按拍板结论 #8 外置在 config/prompts/ (文件即版本, git 管理 changelog)
-- publish_targets 表已建, 一阶段发布走 exporter, 二阶段接 API/RPA 时启用
```

## 素材库文件布局（v3，2026-10-25 第二阶段修订）

`resource/` 是唯一数据根（与代码分离、gitignore、运行时自动创建）。**每篇文章一个项目文件夹**
（初始名 = 输入文章标题-日期时间；创作 Agent 定题后改名为 拟定标题-日期时间）：

```
resource/
├── app.db  style_reference/                  # 范文库（风格蒸馏用）
├── common/                                   # 公共素材库
│   ├── reference/<文章标题>/                  # 公共文章素材（与项目内同级结构）
│   ├── 图片/  视频/  音频/  其他/
│   └── inbox/                                # 手动拷入落点，扫描即入库
└── <输入文章标题-YYYYMMDD-HHmm>/              # 文章项目文件夹
    ├── reference/
    │   ├── <输入文章标题>/  page.html content.md meta.json
    │   └── <参考文章标题>/                    # 与输入文章同级，不做来源隔离
    ├── 图片/  视频/  音频/  其他/
    ├── inbox/                                # 本文手动添加落点
    ├── exports/<platform>/                   # 发布包（xhs_cards/ 也在此）
    ├── drafts/                               # 文案版本 vNNN.md/.json + runs/
    └── notes.md                              # 收集报告
```

> 历史：v1 `articles/<id>` 英文目录；v2 `data/library/` 标题命名中文分项；v3 改 `resource/` 根
> + 项目文件夹（reference 同级 + 产出并入），满足「统一目录、分项保存、创作后随标题改名」。

### 素材摄取流水线（统一入口）

无论来自 Agent 抓取、GUI 上传、还是直接拷进 `inbox/`，都走同一条摄取管线：

```
落盘 → 计算 sha256/phash → 全局去重(命中则建引用不复制)
     → 图片: 尺寸过滤 + 水印检测; 视频: 取时长/封面帧
     → 文本/文档: 抽取正文, 切块入索引
     → 写 materials 行 → 触发 material.ingested 事件
```

`inbox/` 由 watchdog 监听（开发期也可手动点「扫描新素材」），保证「拷文件即入库」。

## 文档块模型（DraftDoc）——编辑器的地基

文案不是一大段 Markdown 字符串，而是**带稳定 id 的有序块列表**（类 Notion 简化版）：

```jsonc
{
  "id": "d_01", "article_id": "a_01", "version": 3,
  "blocks": [
    { "id": "b_1",  "type": "heading",  "level": 1, "text": "..." },
    { "id": "b_2",  "type": "paragraph", "text": "...", "citations": ["m_7"] },
    { "id": "b_3",  "type": "image",    "asset_id": "m_21", "caption": "...", "source": "官方博客" },
    { "id": "b_4",  "type": "quote",    "text": "...", "citations": ["m_9"] },
    { "id": "b_5",  "type": "video",    "asset_id": "m_33" },
    { "id": "b_6",  "type": "divider" }
  ],
  "meta": {
    "keywords": ["..."], "one_liner": "...",
    "title_candidates": ["...", "...", "..."],
    "word_count": 1450,
    "xhs_pages": [ { "title": "...", "block_ids": ["b_2"], "asset_id": "m_21" } ]
  }
}
```

为什么用块模型而不是纯 Markdown：

| 需求 | 块模型如何支撑 |
|---|---|
| 段落级选中重生成 | 直接按 `block_id` 定位重写，不碰其他块 |
| 审稿 checklist 联动高亮 | `review_items.block_id` 精确锚定 |
| 图片替换/去除 | 改 image 块的 `asset_id` 或删块 |
| 小红书分页 | `xhs_pages` 引用块，分页与正文单一事实源 |
| 版本 diff | 块级 diff 比文本 diff 直观 |

**导出**：Markdown（编辑器展示与落盘）、公众号 HTML（doocs/md 主题渲染）、小红书分页 JSON（卡片生成器输入）、微博/X 文本变体。导出是单向的，编辑只改块模型。

## 检索（供创作与审稿）

- 全文：SQLite FTS5（中文用 trigram 分词）覆盖所有文本素材与原文快照。
- 向量：文本块与图片说明 → embedding（可配 bge / provider embedding API）→ sqlite-vec 存储；用于「段落选图」「claims 找证据」「撞稿语义比对」。
- 向量索引失败可整体降级为纯 FTS，不阻断流程。

## 版本与落盘（V1.2 块级增量版本）

- drafts 表只存**稀疏 checkpoint**（创建 v1 / 定稿 / 回滚点）；每次编辑只记 `draft_changes`
  变更块差异（old/new 块快照 + meta diff），不再每版全量备份。
- HEAD = 最近 checkpoint + 后续变更重放（`dao.latest_draft` 透明处理）；任意版本可重建
  （`dao.get_draft(aid, version)`）；回滚 = 重建目标态存为新 checkpoint。
- checkpoint 文件落 `<项目>/drafts/vNNN.md/.json`；Agent 运行记录在 `<项目>/drafts/runs/`。
- 关键词统一 `#关键词` 格式、中文逗号分隔（入库剥离 #）；改主标题联动正文一级标题与项目文件夹改名。

## 开放问题

1. 公共素材库是否需要标签/专辑分类？（初版只有 FTS + 来源搜索，标签列入 M2 候选）
2. 视频素材体积大，是否设单任务素材总上限（默认 500MB 可配）？
