CREATE TABLE IF NOT EXISTS audio_schema(version INTEGER PRIMARY KEY, applied_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS media_products(
 id TEXT PRIMARY KEY, article_id TEXT NOT NULL REFERENCES articles(id), kind TEXT NOT NULL,
 revision INTEGER NOT NULL, doc_json TEXT NOT NULL, created_at REAL NOT NULL,
 UNIQUE(article_id,kind));
CREATE TABLE IF NOT EXISTS media_versions(
 product_id TEXT NOT NULL REFERENCES media_products(id), revision INTEGER NOT NULL,
 doc_json TEXT NOT NULL, editor_id TEXT, created_at REAL NOT NULL, PRIMARY KEY(product_id,revision));
CREATE TABLE IF NOT EXISTS voice_profiles(
 id TEXT PRIMARY KEY, provider TEXT NOT NULL, voice_id TEXT NOT NULL, name TEXT NOT NULL,
 authorization TEXT NOT NULL, projects_json TEXT NOT NULL, verified_at REAL, enabled INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS audio_batches(
 id TEXT PRIMARY KEY, article_id TEXT NOT NULL REFERENCES articles(id), product_id TEXT NOT NULL,
 revision INTEGER NOT NULL, input_hash TEXT NOT NULL, snapshot_json TEXT NOT NULL,
 status TEXT NOT NULL, cancel_requested INTEGER NOT NULL DEFAULT 0, initiator_id TEXT,
 job_id TEXT, error TEXT NOT NULL DEFAULT '', result_json TEXT, created_at REAL NOT NULL, finished_at REAL);
CREATE INDEX IF NOT EXISTS idx_audio_batches_project ON audio_batches(article_id,created_at DESC);
CREATE TABLE IF NOT EXISTS audio_attempts(
 id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES audio_batches(id), paragraph_id TEXT NOT NULL,
 cache_key TEXT NOT NULL, provider TEXT NOT NULL, state TEXT NOT NULL, chars INTEGER NOT NULL,
 sent_at REAL, finished_at REAL, error TEXT NOT NULL DEFAULT '', cost_status TEXT NOT NULL,
 estimated_cost REAL, rate_json TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS audio_segments(
 id TEXT PRIMARY KEY, article_id TEXT NOT NULL REFERENCES articles(id), cache_key TEXT NOT NULL,
 path TEXT NOT NULL, sha256 TEXT NOT NULL, duration REAL NOT NULL, snapshot_json TEXT NOT NULL,
 created_at REAL NOT NULL, UNIQUE(article_id,cache_key));
CREATE TABLE IF NOT EXISTS audio_files(
 id TEXT PRIMARY KEY, article_id TEXT NOT NULL REFERENCES articles(id), batch_id TEXT NOT NULL,
 name TEXT NOT NULL, path TEXT NOT NULL, sha256 TEXT NOT NULL, duration REAL,
 UNIQUE(batch_id,name));
CREATE TABLE IF NOT EXISTS audio_reviews(
 id TEXT PRIMARY KEY, article_id TEXT NOT NULL, product_id TEXT NOT NULL, kind TEXT NOT NULL,
 target_id TEXT NOT NULL, fingerprint TEXT NOT NULL, snapshot_json TEXT NOT NULL,
 submitter_id TEXT, reviewer_id TEXT, status TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
 reason TEXT NOT NULL DEFAULT '', comments_json TEXT NOT NULL DEFAULT '[]', created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS audio_exports(
 article_id TEXT PRIMARY KEY REFERENCES articles(id), batch_id TEXT NOT NULL,
 review_id TEXT NOT NULL, manifest_json TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS audio_settings(key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
