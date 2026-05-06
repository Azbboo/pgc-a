CREATE TABLE IF NOT EXISTS research_experiments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  strategy_version_id INTEGER,
  experiment_key TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  sample_start_date TEXT,
  sample_end_date TEXT,
  validation_start_date TEXT,
  validation_end_date TEXT,
  objective TEXT,
  notes TEXT,
  status TEXT NOT NULL DEFAULT 'running'
    CHECK (status IN ('draft', 'running', 'completed', 'rejected', 'promoted')),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (strategy_version_id) REFERENCES strategy_versions(id)
);

CREATE TABLE IF NOT EXISTS backtest_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  experiment_id INTEGER,
  strategy_version_id INTEGER NOT NULL,
  account_id INTEGER,
  run_key TEXT NOT NULL UNIQUE,
  sample_type TEXT NOT NULL
    CHECK (sample_type IN ('train', 'validation', 'full', 'walk_forward')),
  start_date TEXT NOT NULL,
  end_date TEXT NOT NULL,
  params_hash TEXT NOT NULL,
  input_hash TEXT NOT NULL,
  metrics_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'completed'
    CHECK (status IN ('started', 'completed', 'failed')),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (experiment_id) REFERENCES research_experiments(id),
  FOREIGN KEY (strategy_version_id) REFERENCES strategy_versions(id),
  FOREIGN KEY (account_id) REFERENCES portfolio_accounts(id)
);

CREATE INDEX IF NOT EXISTS idx_backtest_runs_strategy_dates
  ON backtest_runs(strategy_version_id, start_date, end_date);

CREATE TABLE IF NOT EXISTS backtest_trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  backtest_run_id INTEGER NOT NULL,
  signal_id INTEGER,
  ts_code TEXT NOT NULL,
  name TEXT,
  buy_date TEXT NOT NULL,
  buy_price REAL NOT NULL,
  sell_date TEXT,
  sell_price REAL,
  shares INTEGER,
  ret REAL,
  holding_days INTEGER,
  exit_reason TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (backtest_run_id) REFERENCES backtest_runs(id),
  FOREIGN KEY (signal_id) REFERENCES strategy_signals(id)
);

CREATE INDEX IF NOT EXISTS idx_backtest_trades_run
  ON backtest_trades(backtest_run_id);

CREATE VIEW IF NOT EXISTS v_daily_review AS
SELECT
  dp.id AS daily_pick_id,
  sr.id AS strategy_run_id,
  sr.strategy_version,
  dp.review_date,
  dp.planned_buy_date,
  ss.id AS signal_id,
  ss.ts_code,
  ss.name,
  ss.score,
  tp.id AS trade_plan_id,
  tp.account_id,
  tp.action,
  tp.status AS trade_plan_status,
  ad.id AS agent_decision_id,
  ad.action AS agent_action,
  ad.risk_level AS agent_risk_level,
  ad.confidence AS agent_confidence
FROM daily_picks dp
JOIN strategy_runs sr ON sr.id = dp.strategy_run_id
JOIN strategy_signals ss ON ss.id = dp.signal_id
LEFT JOIN trade_plans tp ON tp.daily_pick_id = dp.id
LEFT JOIN agent_decisions ad ON ad.daily_pick_id = dp.id;

CREATE VIEW IF NOT EXISTS v_open_positions AS
SELECT
  p.id AS position_id,
  p.account_id,
  p.signal_id,
  p.ts_code,
  p.name,
  p.buy_date,
  p.buy_price,
  p.shares,
  p.cost,
  p.planned_t2_date,
  p.planned_t5_date,
  p.status,
  mb.trade_date AS latest_trade_date,
  mb.close AS latest_close
FROM positions p
LEFT JOIN market_bars mb
  ON mb.ts_code = p.ts_code
 AND mb.trade_date = (
    SELECT MAX(mb2.trade_date)
    FROM market_bars mb2
    WHERE mb2.ts_code = p.ts_code
 )
WHERE p.status NOT IN ('closed', 'cancelled');
