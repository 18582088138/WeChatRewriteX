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
CREATE UNIQUE INDEX IF NOT EXISTS idx_materials_sha ON materials(sha256) WHERE sha256 IS NOT NULL;

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
  origin        TEXT DEFAULT 'agent',      -- agent|human|auto_fix|insert_refs
  created_at    TEXT DEFAULT (datetime('now', 'localtime')),
  UNIQUE(article_id, version)
);
CREATE INDEX IF NOT EXISTS idx_drafts_article ON drafts(article_id, version DESC);

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
