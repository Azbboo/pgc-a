CREATE TABLE IF NOT EXISTS trade_plans (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id INTEGER NOT NULL,
  daily_pick_id INTEGER,
  signal_id INTEGER,
  agent_decision_id INTEGER,
  as_of_date TEXT NOT NULL,
  planned_trade_date TEXT,
  planned_buy_date TEXT,
  action TEXT NOT NULL
    CHECK (action IN ('buy_next_open', 'skip_no_cash', 'skip_max_positions', 'skip_agent_risk', 'skip_manual', 'hold', 'sell_t2_take_profit', 'sell_t2_stop_loss', 'sell_t5_timeout', 'manual_review')),
  reason TEXT,
  plan_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft', 'active', 'executed', 'skipped', 'cancelled', 'expired', 'superseded')),
  cancel_reason TEXT,
  operator TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT,
  FOREIGN KEY (account_id) REFERENCES portfolio_accounts(id),
  FOREIGN KEY (daily_pick_id) REFERENCES daily_picks(id),
  FOREIGN KEY (signal_id) REFERENCES strategy_signals(id),
  FOREIGN KEY (agent_decision_id) REFERENCES agent_decisions(id)
);

CREATE INDEX IF NOT EXISTS idx_trade_plans_account_date
  ON trade_plans(account_id, as_of_date);

CREATE INDEX IF NOT EXISTS idx_trade_plans_status_date
  ON trade_plans(status, planned_trade_date);

CREATE UNIQUE INDEX IF NOT EXISTS uq_trade_plans_active_buy_signal
  ON trade_plans(account_id, signal_id, action)
  WHERE status IN ('draft', 'active') AND action = 'buy_next_open';

CREATE TABLE IF NOT EXISTS trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id INTEGER NOT NULL,
  trade_plan_id INTEGER,
  signal_id INTEGER,
  agent_decision_id INTEGER,
  ts_code TEXT NOT NULL,
  name TEXT NOT NULL,
  side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
  planned_date TEXT,
  executed_date TEXT,
  executed_price REAL CHECK (executed_price IS NULL OR executed_price > 0),
  amount REAL CHECK (amount IS NULL OR amount >= 0),
  shares INTEGER CHECK (shares IS NULL OR shares >= 0),
  fee REAL NOT NULL DEFAULT 0 CHECK (fee >= 0),
  tax REAL NOT NULL DEFAULT 0 CHECK (tax >= 0),
  slippage REAL,
  status TEXT NOT NULL DEFAULT 'planned'
    CHECK (status IN ('planned', 'executed', 'partial', 'cancelled', 'corrected', 'reversed')),
  source TEXT NOT NULL DEFAULT 'manual'
    CHECK (source IN ('model', 'paper_model', 'manual', 'broker_import', 'correction')),
  correction_of_trade_id INTEGER,
  operator TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT,
  FOREIGN KEY (account_id) REFERENCES portfolio_accounts(id),
  FOREIGN KEY (trade_plan_id) REFERENCES trade_plans(id),
  FOREIGN KEY (signal_id) REFERENCES strategy_signals(id),
  FOREIGN KEY (agent_decision_id) REFERENCES agent_decisions(id),
  FOREIGN KEY (correction_of_trade_id) REFERENCES trades(id)
);

CREATE INDEX IF NOT EXISTS idx_trades_account_date
  ON trades(account_id, executed_date);

CREATE INDEX IF NOT EXISTS idx_trades_plan
  ON trades(trade_plan_id);

CREATE INDEX IF NOT EXISTS idx_trades_signal
  ON trades(signal_id);

CREATE TABLE IF NOT EXISTS positions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id INTEGER NOT NULL,
  signal_id INTEGER,
  entry_trade_id INTEGER NOT NULL,
  exit_trade_id INTEGER,
  ts_code TEXT NOT NULL,
  name TEXT NOT NULL,
  buy_date TEXT NOT NULL,
  buy_price REAL NOT NULL CHECK (buy_price > 0),
  shares INTEGER NOT NULL CHECK (shares >= 0),
  cost REAL NOT NULL CHECK (cost >= 0),
  planned_t2_date TEXT,
  planned_t5_date TEXT,
  status TEXT NOT NULL DEFAULT 'waiting_t2'
    CHECK (status IN ('open', 'waiting_t2', 'need_t2_decision', 'holding_to_t5', 'need_t5_exit', 'planned_exit', 'partially_closed', 'closed', 'cancelled')),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  closed_at TEXT,
  FOREIGN KEY (account_id) REFERENCES portfolio_accounts(id),
  FOREIGN KEY (signal_id) REFERENCES strategy_signals(id),
  FOREIGN KEY (entry_trade_id) REFERENCES trades(id),
  FOREIGN KEY (exit_trade_id) REFERENCES trades(id)
);

CREATE INDEX IF NOT EXISTS idx_positions_account_status
  ON positions(account_id, status);

CREATE INDEX IF NOT EXISTS idx_positions_t2_t5
  ON positions(planned_t2_date, planned_t5_date);

CREATE TABLE IF NOT EXISTS exit_decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  position_id INTEGER NOT NULL,
  account_id INTEGER NOT NULL,
  decision_date TEXT NOT NULL,
  decision_stage TEXT NOT NULL
    CHECK (decision_stage IN ('t2', 't5', 'manual')),
  decision TEXT NOT NULL
    CHECK (decision IN ('pending', 'take_profit', 'stop_loss', 'hold_to_t5', 'timeout_exit', 'manual_override', 'executed')),
  ret REAL,
  reason TEXT NOT NULL
    CHECK (reason IN ('take_profit_ge3', 'stop_loss_le_neg3', 'hold_middle_to_t5', 'timeout_t5', 'manual_override', 'pending')),
  planned_exit_date TEXT,
  generated_trade_plan_id INTEGER,
  executed_exit_trade_id INTEGER,
  operator TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (position_id) REFERENCES positions(id),
  FOREIGN KEY (account_id) REFERENCES portfolio_accounts(id),
  FOREIGN KEY (generated_trade_plan_id) REFERENCES trade_plans(id),
  FOREIGN KEY (executed_exit_trade_id) REFERENCES trades(id)
);

CREATE INDEX IF NOT EXISTS idx_exit_decisions_account_date
  ON exit_decisions(account_id, decision_date);

CREATE UNIQUE INDEX IF NOT EXISTS uq_exit_decision_position_stage_date
  ON exit_decisions(position_id, decision_stage, decision_date)
  WHERE decision <> 'executed';

CREATE TABLE IF NOT EXISTS equity_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id INTEGER NOT NULL,
  as_of_date TEXT NOT NULL,
  snapshot_type TEXT NOT NULL DEFAULT 'close'
    CHECK (snapshot_type IN ('open', 'intraday', 'close', 'after_trade', 'manual_adjustment')),
  cash REAL NOT NULL,
  market_value REAL NOT NULL,
  total_equity REAL NOT NULL,
  realized_pnl REAL,
  unrealized_pnl REAL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (account_id) REFERENCES portfolio_accounts(id),
  UNIQUE(account_id, as_of_date, snapshot_type)
);

CREATE INDEX IF NOT EXISTS idx_equity_snapshots_account_date
  ON equity_snapshots(account_id, as_of_date);
