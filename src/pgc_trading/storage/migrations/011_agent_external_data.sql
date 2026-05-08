CREATE TABLE IF NOT EXISTS agent_external_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts_code TEXT NOT NULL,
  published_date TEXT NOT NULL
    CHECK (length(published_date) = 8 AND published_date NOT GLOB '*[^0-9]*'),
  item_type TEXT NOT NULL
    CHECK (item_type IN ('news', 'announcement', 'fundamental', 'sentiment', 'risk_note', 'research_note')),
  provider TEXT NOT NULL,
  title TEXT NOT NULL,
  summary TEXT NOT NULL,
  url TEXT,
  sentiment TEXT NOT NULL DEFAULT 'unknown'
    CHECK (sentiment IN ('positive', 'neutral', 'negative', 'mixed', 'unknown')),
  importance TEXT NOT NULL DEFAULT 'unknown'
    CHECK (importance IN ('low', 'medium', 'high', 'unknown')),
  metadata_json TEXT NOT NULL DEFAULT '{}',
  source_hash TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(provider, source_hash)
);

CREATE INDEX IF NOT EXISTS idx_agent_external_items_code_date
  ON agent_external_items(ts_code, published_date);

CREATE INDEX IF NOT EXISTS idx_agent_external_items_type_date
  ON agent_external_items(item_type, published_date);
