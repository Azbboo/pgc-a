CREATE TABLE IF NOT EXISTS market_diagnostic_bars (
  ts_code TEXT NOT NULL,
  trade_date TEXT NOT NULL,
  provider TEXT NOT NULL,
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
  fetch_run_id INTEGER,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (provider, ts_code, trade_date),
  FOREIGN KEY (fetch_run_id) REFERENCES market_fetch_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_market_diagnostic_bars_trade_date
  ON market_diagnostic_bars(provider, trade_date);

CREATE INDEX IF NOT EXISTS idx_market_diagnostic_bars_fetch_run
  ON market_diagnostic_bars(fetch_run_id);
