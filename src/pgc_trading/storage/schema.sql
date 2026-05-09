PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS raw_events (
  id INTEGER PRIMARY KEY,
  ts_code TEXT NOT NULL,
  code TEXT,
  name TEXT NOT NULL,
  entry_date TEXT NOT NULL,
  entry_time TEXT,
  entry_price REAL NOT NULL,
  source TEXT DEFAULT 'pgc_pool',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(ts_code, entry_date, entry_time, entry_price)
);

CREATE TABLE IF NOT EXISTS market_bars (
  ts_code TEXT NOT NULL,
  trade_date TEXT NOT NULL,
  open REAL,
  high REAL,
  low REAL,
  close REAL,
  amount REAL,
  adj_factor REAL,
  adj_open REAL,
  adj_high REAL,
  adj_low REAL,
  adj_close REAL,
  source TEXT DEFAULT 'tushare',
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (ts_code, trade_date)
);

CREATE TABLE IF NOT EXISTS strategy_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  strategy_id TEXT NOT NULL,
  strategy_version TEXT NOT NULL,
  as_of_date TEXT NOT NULL,
  params_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS signals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL REFERENCES strategy_runs(id),
  event_id INTEGER REFERENCES raw_events(id),
  ts_code TEXT NOT NULL,
  name TEXT NOT NULL,
  review_date TEXT NOT NULL,
  buy_date TEXT,
  score REAL NOT NULL,
  features_json TEXT NOT NULL,
  is_daily_pick INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_signals_review_date ON signals(review_date);
CREATE INDEX IF NOT EXISTS idx_signals_ts_code ON signals(ts_code);

CREATE TABLE IF NOT EXISTS input_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  as_of_date TEXT NOT NULL,
  snapshot_type TEXT NOT NULL,
  source_refs_json TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  agent_system TEXT NOT NULL,
  agent_version TEXT,
  signal_id INTEGER REFERENCES signals(id),
  input_snapshot_id INTEGER REFERENCES input_snapshots(id),
  as_of_date TEXT NOT NULL,
  config_json TEXT NOT NULL,
  config_hash TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'planned',
  started_at TEXT,
  finished_at TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_signal ON agent_runs(signal_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_as_of_date ON agent_runs(as_of_date);

CREATE TABLE IF NOT EXISTS agent_artifacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  agent_run_id INTEGER NOT NULL REFERENCES agent_runs(id),
  artifact_type TEXT NOT NULL,
  path TEXT NOT NULL,
  content_hash TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  agent_run_id INTEGER NOT NULL REFERENCES agent_runs(id),
  signal_id INTEGER REFERENCES signals(id),
  action TEXT,
  confidence REAL,
  risk_level TEXT,
  summary TEXT,
  raw_decision_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS portfolio_accounts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_key TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  account_type TEXT NOT NULL
    CHECK (account_type IN ('backtest', 'paper', 'live')),
  initial_cash REAL NOT NULL CHECK (initial_cash >= 0),
  max_positions INTEGER NOT NULL CHECK (max_positions >= 0),
  position_sizing TEXT NOT NULL DEFAULT 'equal_slots'
    CHECK (position_sizing IN ('equal_slots', 'fixed_cash', 'manual')),
  status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('active', 'paused', 'closed')),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id INTEGER NOT NULL REFERENCES portfolio_accounts(id),
  signal_id INTEGER REFERENCES signals(id),
  agent_decision_id INTEGER REFERENCES agent_decisions(id),
  ts_code TEXT NOT NULL,
  name TEXT NOT NULL,
  side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
  planned_date TEXT,
  executed_date TEXT,
  price REAL,
  amount REAL,
  shares INTEGER,
  status TEXT NOT NULL DEFAULT 'planned',
  source TEXT NOT NULL DEFAULT 'model',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trade_plans (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id INTEGER NOT NULL REFERENCES portfolio_accounts(id),
  signal_id INTEGER REFERENCES signals(id),
  agent_decision_id INTEGER REFERENCES agent_decisions(id),
  as_of_date TEXT NOT NULL,
  planned_buy_date TEXT,
  action TEXT NOT NULL,
  reason TEXT,
  plan_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS positions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id INTEGER NOT NULL REFERENCES portfolio_accounts(id),
  signal_id INTEGER REFERENCES signals(id),
  ts_code TEXT NOT NULL,
  name TEXT NOT NULL,
  buy_date TEXT NOT NULL,
  buy_price REAL NOT NULL,
  shares INTEGER NOT NULL,
  cost REAL NOT NULL,
  planned_t2_date TEXT,
  planned_t5_date TEXT,
  status TEXT NOT NULL DEFAULT 'open',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_positions_account_status ON positions(account_id, status);

CREATE TABLE IF NOT EXISTS exits (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  position_id INTEGER NOT NULL REFERENCES positions(id),
  decision_date TEXT NOT NULL,
  decision_stage TEXT NOT NULL,
  ret REAL,
  reason TEXT,
  planned_exit_date TEXT,
  executed_exit_date TEXT,
  executed_price REAL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS equity_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id INTEGER NOT NULL REFERENCES portfolio_accounts(id),
  as_of_date TEXT NOT NULL,
  cash REAL NOT NULL,
  market_value REAL NOT NULL,
  total_equity REAL NOT NULL,
  realized_pnl REAL,
  unrealized_pnl REAL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(account_id, as_of_date)
);

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
