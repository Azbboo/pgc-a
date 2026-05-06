CREATE TABLE IF NOT EXISTS raw_import_batches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_file TEXT NOT NULL,
  source_hash TEXT NOT NULL UNIQUE,
  source_type TEXT NOT NULL DEFAULT 'pgc_pool',
  imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  row_count INTEGER NOT NULL DEFAULT 0 CHECK (row_count >= 0),
  valid_count INTEGER NOT NULL DEFAULT 0 CHECK (valid_count >= 0),
  dirty_count INTEGER NOT NULL DEFAULT 0 CHECK (dirty_count >= 0),
  status TEXT NOT NULL DEFAULT 'completed'
    CHECK (status IN ('started', 'completed', 'failed', 'invalidated')),
  notes TEXT
);

CREATE TABLE IF NOT EXISTS raw_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  import_batch_id INTEGER,
  ts_code TEXT NOT NULL,
  code TEXT,
  name TEXT NOT NULL,
  entry_date TEXT NOT NULL,
  entry_time TEXT,
  entry_price REAL NOT NULL CHECK (entry_price > 0),
  source TEXT NOT NULL DEFAULT 'pgc_pool',
  is_valid INTEGER NOT NULL DEFAULT 1 CHECK (is_valid IN (0, 1)),
  invalid_reason TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT,
  FOREIGN KEY (import_batch_id) REFERENCES raw_import_batches(id),
  UNIQUE(ts_code, entry_date, entry_time, entry_price)
);

CREATE INDEX IF NOT EXISTS idx_raw_events_entry_date
  ON raw_events(entry_date);

CREATE INDEX IF NOT EXISTS idx_raw_events_valid_ts_code
  ON raw_events(is_valid, ts_code);

CREATE TABLE IF NOT EXISTS market_fetch_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider TEXT NOT NULL DEFAULT 'tushare',
  start_date TEXT,
  end_date TEXT NOT NULL,
  ts_code_count INTEGER NOT NULL DEFAULT 0 CHECK (ts_code_count >= 0),
  status TEXT NOT NULL DEFAULT 'completed'
    CHECK (status IN ('started', 'completed', 'partial_success', 'failed')),
  manifest_json TEXT,
  error_message TEXT,
  fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_market_fetch_runs_provider_end
  ON market_fetch_runs(provider, end_date);

CREATE TABLE IF NOT EXISTS trade_calendar (
  exchange TEXT NOT NULL DEFAULT 'SSE',
  cal_date TEXT NOT NULL,
  is_open INTEGER NOT NULL CHECK (is_open IN (0, 1)),
  pretrade_date TEXT,
  provider TEXT NOT NULL DEFAULT 'tushare',
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (exchange, cal_date)
);

CREATE INDEX IF NOT EXISTS idx_trade_calendar_open_date
  ON trade_calendar(is_open, cal_date);

CREATE TABLE IF NOT EXISTS market_bars (
  ts_code TEXT NOT NULL,
  trade_date TEXT NOT NULL,
  open REAL CHECK (open >= 0),
  high REAL CHECK (high >= 0),
  low REAL CHECK (low >= 0),
  close REAL CHECK (close >= 0),
  vol REAL CHECK (vol >= 0),
  amount REAL CHECK (amount >= 0),
  adj_factor REAL,
  adj_open REAL,
  adj_high REAL,
  adj_low REAL,
  adj_close REAL,
  provider TEXT NOT NULL DEFAULT 'tushare',
  fetch_run_id INTEGER,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (ts_code, trade_date),
  FOREIGN KEY (fetch_run_id) REFERENCES market_fetch_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_market_bars_trade_date
  ON market_bars(trade_date);

CREATE INDEX IF NOT EXISTS idx_market_bars_fetch_run
  ON market_bars(fetch_run_id);

CREATE TABLE IF NOT EXISTS daily_basic_snapshots (
  ts_code TEXT NOT NULL,
  trade_date TEXT NOT NULL,
  turnover_rate REAL,
  turnover_rate_f REAL,
  volume_ratio REAL,
  pe REAL,
  pe_ttm REAL,
  pb REAL,
  ps REAL,
  ps_ttm REAL,
  dv_ratio REAL,
  total_share REAL,
  float_share REAL,
  free_share REAL,
  total_mv REAL,
  circ_mv REAL,
  provider TEXT NOT NULL DEFAULT 'tushare',
  fetch_run_id INTEGER,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (ts_code, trade_date),
  FOREIGN KEY (fetch_run_id) REFERENCES market_fetch_runs(id)
);
