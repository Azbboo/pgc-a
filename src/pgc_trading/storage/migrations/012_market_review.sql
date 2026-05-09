CREATE TABLE IF NOT EXISTS market_review_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  as_of_date TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('started', 'completed', 'failed')),
  provider_manifest_json TEXT NOT NULL DEFAULT '{}',
  coverage_json TEXT NOT NULL DEFAULT '{}',
  summary_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  completed_at TEXT,
  UNIQUE(as_of_date)
);

CREATE INDEX IF NOT EXISTS idx_market_review_runs_as_of_date
  ON market_review_runs(as_of_date);

CREATE TABLE IF NOT EXISTS market_regime_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  market_review_run_id INTEGER NOT NULL,
  as_of_date TEXT NOT NULL,
  regime TEXT NOT NULL CHECK (regime IN ('risk_on', 'neutral', 'risk_off', 'unknown')),
  breadth_score REAL,
  trend_score REAL,
  volume_score REAL,
  sentiment_score REAL,
  persistence_score REAL,
  summary TEXT NOT NULL,
  metrics_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY (market_review_run_id) REFERENCES market_review_runs(id),
  UNIQUE(market_review_run_id)
);

CREATE INDEX IF NOT EXISTS idx_market_regime_snapshots_date
  ON market_regime_snapshots(as_of_date);

CREATE TABLE IF NOT EXISTS sector_daily_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  market_review_run_id INTEGER NOT NULL,
  as_of_date TEXT NOT NULL,
  sector_code TEXT NOT NULL,
  sector_name TEXT NOT NULL,
  provider TEXT NOT NULL,
  rank_overall INTEGER,
  return_1d REAL,
  return_3d REAL,
  return_5d REAL,
  return_10d REAL,
  breadth_score REAL,
  volume_score REAL,
  persistence_score REAL,
  leader_count INTEGER NOT NULL DEFAULT 0,
  metrics_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY (market_review_run_id) REFERENCES market_review_runs(id),
  UNIQUE(market_review_run_id, sector_code)
);

CREATE INDEX IF NOT EXISTS idx_sector_daily_snapshots_date_rank
  ON sector_daily_snapshots(as_of_date, rank_overall);

CREATE INDEX IF NOT EXISTS idx_sector_daily_snapshots_sector
  ON sector_daily_snapshots(sector_code, as_of_date);

CREATE TABLE IF NOT EXISTS sector_constituents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  market_review_run_id INTEGER NOT NULL,
  sector_code TEXT NOT NULL,
  sector_name TEXT NOT NULL,
  ts_code TEXT NOT NULL,
  name TEXT,
  rank_in_sector INTEGER,
  role TEXT NOT NULL DEFAULT 'member'
    CHECK (role IN ('leader', 'follower', 'member', 'weak')),
  score REAL,
  metrics_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY (market_review_run_id) REFERENCES market_review_runs(id),
  UNIQUE(market_review_run_id, sector_code, ts_code)
);

CREATE INDEX IF NOT EXISTS idx_sector_constituents_stock
  ON sector_constituents(ts_code);

CREATE INDEX IF NOT EXISTS idx_sector_constituents_sector_rank
  ON sector_constituents(sector_code, rank_in_sector);

CREATE TABLE IF NOT EXISTS market_external_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  as_of_date TEXT NOT NULL,
  scope_type TEXT NOT NULL CHECK (scope_type IN ('market', 'sector', 'stock')),
  scope_key TEXT NOT NULL,
  item_type TEXT NOT NULL
    CHECK (item_type IN ('news', 'announcement', 'sentiment', 'policy', 'risk_note', 'research_note')),
  provider TEXT NOT NULL,
  title TEXT NOT NULL,
  summary TEXT NOT NULL,
  url TEXT,
  sentiment TEXT NOT NULL DEFAULT 'unknown'
    CHECK (sentiment IN ('positive', 'neutral', 'negative', 'mixed', 'unknown')),
  importance TEXT NOT NULL DEFAULT 'unknown'
    CHECK (importance IN ('low', 'medium', 'high', 'unknown')),
  published_date TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  source_hash TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(provider, source_hash)
);

CREATE INDEX IF NOT EXISTS idx_market_external_items_date_scope
  ON market_external_items(as_of_date, scope_type, scope_key);

CREATE INDEX IF NOT EXISTS idx_market_external_items_stock_date
  ON market_external_items(scope_key, as_of_date)
  WHERE scope_type = 'stock';

CREATE TABLE IF NOT EXISTS market_plan_contexts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  market_review_run_id INTEGER NOT NULL,
  trade_plan_id INTEGER NOT NULL,
  alignment TEXT NOT NULL
    CHECK (alignment IN ('aligned', 'neutral', 'conflict', 'unknown')),
  risk_level TEXT NOT NULL
    CHECK (risk_level IN ('low', 'medium', 'high', 'unknown')),
  management_action TEXT NOT NULL
    CHECK (management_action IN ('proceed', 'manual_review', 'consider_cancel', 'unknown')),
  rationale TEXT NOT NULL,
  evidence_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (market_review_run_id) REFERENCES market_review_runs(id),
  FOREIGN KEY (trade_plan_id) REFERENCES trade_plans(id),
  UNIQUE(market_review_run_id, trade_plan_id)
);

CREATE INDEX IF NOT EXISTS idx_market_plan_contexts_plan
  ON market_plan_contexts(trade_plan_id);

CREATE TABLE IF NOT EXISTS strategy_hypotheses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  as_of_date TEXT NOT NULL,
  hypothesis_type TEXT NOT NULL,
  title TEXT NOT NULL,
  rationale TEXT NOT NULL,
  evidence_json TEXT NOT NULL DEFAULT '{}',
  proposed_change_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'proposed'
    CHECK (status IN ('proposed', 'testing', 'accepted', 'rejected', 'archived')),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_strategy_hypotheses_date_status
  ON strategy_hypotheses(as_of_date, status);
