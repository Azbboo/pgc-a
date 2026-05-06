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
  name TEXT NOT NULL UNIQUE,
  account_type TEXT NOT NULL DEFAULT 'paper',
  initial_cash REAL NOT NULL,
  max_positions INTEGER NOT NULL,
  position_sizing TEXT NOT NULL DEFAULT 'equal_slots',
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
