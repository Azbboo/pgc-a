CREATE TABLE IF NOT EXISTS feature_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  feature_version TEXT NOT NULL,
  as_of_date TEXT NOT NULL,
  input_market_fetch_run_id INTEGER,
  status TEXT NOT NULL DEFAULT 'completed'
    CHECK (status IN ('started', 'completed', 'partial_success', 'failed')),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  error_message TEXT,
  FOREIGN KEY (input_market_fetch_run_id) REFERENCES market_fetch_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_feature_runs_date_version
  ON feature_runs(as_of_date, feature_version);

CREATE TABLE IF NOT EXISTS feature_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  feature_run_id INTEGER NOT NULL,
  raw_event_id INTEGER NOT NULL,
  ts_code TEXT NOT NULL,
  review_date TEXT NOT NULL,
  feature_version TEXT NOT NULL,
  features_json TEXT NOT NULL,
  input_hash TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (feature_run_id) REFERENCES feature_runs(id),
  FOREIGN KEY (raw_event_id) REFERENCES raw_events(id),
  UNIQUE(feature_run_id, raw_event_id, review_date)
);

CREATE INDEX IF NOT EXISTS idx_feature_snapshots_event_date
  ON feature_snapshots(raw_event_id, review_date);

CREATE INDEX IF NOT EXISTS idx_feature_snapshots_ts_code_date
  ON feature_snapshots(ts_code, review_date);

CREATE TABLE IF NOT EXISTS strategy_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  strategy_version_id INTEGER NOT NULL,
  strategy_key TEXT NOT NULL,
  strategy_version TEXT NOT NULL,
  as_of_date TEXT NOT NULL,
  params_json TEXT NOT NULL,
  params_hash TEXT NOT NULL,
  feature_run_id INTEGER,
  run_type TEXT NOT NULL DEFAULT 'paper'
    CHECK (run_type IN ('research', 'backtest', 'validation', 'paper', 'live')),
  status TEXT NOT NULL DEFAULT 'completed'
    CHECK (status IN ('started', 'completed', 'partial_success', 'failed')),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  error_message TEXT,
  FOREIGN KEY (strategy_version_id) REFERENCES strategy_versions(id),
  FOREIGN KEY (feature_run_id) REFERENCES feature_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_strategy_runs_version_date
  ON strategy_runs(strategy_version, as_of_date);

CREATE TABLE IF NOT EXISTS strategy_signals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  strategy_run_id INTEGER NOT NULL,
  feature_snapshot_id INTEGER,
  raw_event_id INTEGER,
  ts_code TEXT NOT NULL,
  name TEXT NOT NULL,
  review_date TEXT NOT NULL,
  planned_buy_date TEXT,
  score REAL NOT NULL,
  signal_rank INTEGER,
  signal_status TEXT NOT NULL DEFAULT 'candidate'
    CHECK (signal_status IN ('candidate', 'daily_pick', 'skipped_duplicate', 'skipped_low_score', 'invalid_insufficient_data')),
  features_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (strategy_run_id) REFERENCES strategy_runs(id),
  FOREIGN KEY (feature_snapshot_id) REFERENCES feature_snapshots(id),
  FOREIGN KEY (raw_event_id) REFERENCES raw_events(id)
);

CREATE INDEX IF NOT EXISTS idx_strategy_signals_review_date
  ON strategy_signals(review_date);

CREATE INDEX IF NOT EXISTS idx_strategy_signals_ts_code
  ON strategy_signals(ts_code);

CREATE INDEX IF NOT EXISTS idx_strategy_signals_run_rank
  ON strategy_signals(strategy_run_id, signal_rank);

CREATE TABLE IF NOT EXISTS daily_picks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  strategy_run_id INTEGER NOT NULL,
  signal_id INTEGER NOT NULL,
  review_date TEXT NOT NULL,
  planned_buy_date TEXT,
  score REAL NOT NULL,
  selection_reason TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (strategy_run_id) REFERENCES strategy_runs(id),
  FOREIGN KEY (signal_id) REFERENCES strategy_signals(id),
  UNIQUE(strategy_run_id, review_date)
);

CREATE INDEX IF NOT EXISTS idx_daily_picks_review_date
  ON daily_picks(review_date);
