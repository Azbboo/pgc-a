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

CREATE INDEX IF NOT EXISTS idx_portfolio_accounts_type
  ON portfolio_accounts(account_type, status);
