PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS articles (
  id            TEXT PRIMARY KEY,
  url           TEXT NOT NULL,
  title         TEXT DEFAULT '',
  source_site   TEXT DEFAULT '',
  published_at  TEXT,
  status        TEXT NOT NULL DEFAULT 'NEW',
  style_pack    TEXT,
  target_word_count INTEGER,
  user_notes    TEXT DEFAULT '',
  lib_dir       TEXT,                      -- 项目文件夹名(标题_日期时间)
  selected_json TEXT DEFAULT '[]',         -- 创作会话勾选素材集合
  error         TEXT,
  created_at    TEXT DEFAULT (datetime('now', 'localtime')),
  updated_at    TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS materials (
  id            TEXT PRIMARY KEY,
  scope         TEXT NOT NULL,             -- article | common
  article_id    TEXT,                      -- scope=article 时归属
  kind          TEXT NOT NULL,             -- text|image|video|doc|link
  path          TEXT,                      -- 库内相对路径
  sha256        TEXT,
  phash         TEXT,
  source_url    TEXT,
  source_material_id TEXT,
  watermark     INTEGER,                   -- 0/1/NULL
  width         INTEGER,
  height        INTEGER,
  duration      REAL,
  ref_type      TEXT,                      -- primary|reference|foundational
  fetch_status  TEXT DEFAULT 'ok',         -- ok|fetch_error
  note          TEXT DEFAULT '',
  title         TEXT DEFAULT '',
  meta_json     TEXT DEFAULT '{}',
  created_at    TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_materials_article ON materials(article_id);
CREATE INDEX IF NOT EXISTS idx_materials_scope ON materials(scope, kind);
-- sha256 不做唯一约束：显式「复制到本文素材库」会合法产生第二行同 sha 记录；
-- 去重由 ingest 流程先查后插保证。
CREATE INDEX IF NOT EXISTS idx_materials_sha ON materials(sha256);

CREATE TABLE IF NOT EXISTS material_texts (  -- 文本型素材的正文(供检索/审稿取证)
  material_id   TEXT PRIMARY KEY,
  content       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS drafts (
  id            TEXT PRIMARY KEY,
  article_id    TEXT NOT NULL,
  version       INTEGER NOT NULL,
  doc_json      TEXT NOT NULL,
  keywords_json TEXT DEFAULT '[]',
  one_liner     TEXT DEFAULT '',
  title_candidates_json TEXT DEFAULT '[]',
  word_count    INTEGER DEFAULT 0,
  status        TEXT DEFAULT 'editing',    -- editing|finalized
  parent_version INTEGER,
  origin        TEXT DEFAULT 'agent',      -- agent|human|auto_fix|insert_refs|manual|finalized|rollback
  note          TEXT DEFAULT '',           -- 主动保存版本的备注（V1.4）
  created_at    TEXT DEFAULT (datetime('now', 'localtime')),
  UNIQUE(article_id, version)
);
CREATE INDEX IF NOT EXISTS idx_drafts_article ON drafts(article_id, version DESC);

-- 一篇文稿只有一个可变工作副本；定稿后封存到 drafts，旧增量历史只读兼容。
CREATE TABLE IF NOT EXISTS draft_workspaces (
  article_id TEXT PRIMARY KEY,
  version INTEGER NOT NULL,
  doc_json TEXT NOT NULL,
  origin TEXT NOT NULL,
  note TEXT DEFAULT '',
  created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

-- 块级增量版本（类 Git）：drafts 仅存稀疏 checkpoint（创建/定稿/回滚点），
-- 每次编辑只记变更块的差异；HEAD = 最近 checkpoint + 后续变更重放。
CREATE TABLE IF NOT EXISTS draft_changes (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  article_id    TEXT NOT NULL,
  seq           INTEGER NOT NULL,          -- 全文档单调递增的保存序号（= 对外版本号）
  block_id      TEXT NOT NULL,
  op            TEXT NOT NULL,             -- update|insert|remove|replace_image|set_caption|meta|rollback
  old_json      TEXT,                      -- 变更前块/元信息快照
  new_json      TEXT,                      -- 变更后
  origin        TEXT DEFAULT 'human',
  created_at    TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_changes_article ON draft_changes(article_id, seq);

CREATE TABLE IF NOT EXISTS reviews (
  id            TEXT PRIMARY KEY,
  article_id    TEXT NOT NULL,
  draft_id      TEXT NOT NULL,
  draft_version INTEGER NOT NULL,
  scores_json   TEXT DEFAULT '{}',
  created_at    TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS review_items (
  id            TEXT PRIMARY KEY,
  review_id     TEXT NOT NULL,
  category      TEXT NOT NULL,
  severity      TEXT NOT NULL,
  block_id      TEXT,
  message       TEXT NOT NULL,
  suggestion    TEXT DEFAULT '',
  evidence_json TEXT DEFAULT '[]',
  auto_fixable  INTEGER DEFAULT 0,
  status        TEXT DEFAULT 'pending',    -- pending|accepted|dismissed|fixed
  resolved_by   TEXT,
  resolved_note TEXT
);
CREATE INDEX IF NOT EXISTS idx_ri_review ON review_items(review_id);

CREATE TABLE IF NOT EXISTS publish_targets (
  id            TEXT PRIMARY KEY,
  platform      TEXT NOT NULL,
  account_label TEXT DEFAULT '',
  mode          TEXT DEFAULT 'export',     -- api|rpa|export
  capabilities_json TEXT DEFAULT '{}',
  enabled       INTEGER DEFAULT 1,
  config_json   TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS publish_jobs (
  id            TEXT PRIMARY KEY,
  article_id    TEXT NOT NULL,
  draft_id      TEXT NOT NULL,
  target_id     TEXT,
  platform      TEXT NOT NULL,
  variant_json  TEXT DEFAULT '{}',
  status        TEXT DEFAULT 'pending',    -- pending|done|failed
  result_json   TEXT DEFAULT '{}',
  created_at    TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS jobs (
  id            TEXT PRIMARY KEY,
  type          TEXT NOT NULL,             -- collect|rewrite|review|publish|ingest
  article_id    TEXT,
  payload_json  TEXT DEFAULT '{}',
  status        TEXT DEFAULT 'pending',    -- pending|running|done|failed
  attempts      INTEGER DEFAULT 0,
  run_after     REAL DEFAULT 0,
  result_json   TEXT DEFAULT '{}',
  error         TEXT,
  created_at    TEXT DEFAULT (datetime('now', 'localtime')),
  updated_at    TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, run_after);

CREATE TABLE IF NOT EXISTS llm_calls (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  article_id    TEXT,
  stage         TEXT,
  channel       TEXT,
  model         TEXT,
  prompt_tokens INTEGER DEFAULT 0,
  completion_tokens INTEGER DEFAULT 0,
  latency_ms    INTEGER DEFAULT 0,
  cost_est      REAL DEFAULT 0,
  ok            INTEGER DEFAULT 1,
  created_at    TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS settings (
  key           TEXT PRIMARY KEY,
  value_json    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS embeddings (
  material_id   TEXT PRIMARY KEY,          -- 或 draft block 派生文本 id
  dim           INTEGER NOT NULL,
  vector        BLOB NOT NULL              -- float32 小端字节序
);
