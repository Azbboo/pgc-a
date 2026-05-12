CREATE TABLE IF NOT EXISTS decision_action_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  operation_request_id INTEGER UNIQUE,
  account_id INTEGER NOT NULL,
  review_date TEXT NOT NULL,
  execution_date TEXT,
  cockpit_status TEXT NOT NULL DEFAULT 'review_required'
    CHECK (cockpit_status IN ('ready', 'review_required', 'blocked', 'unknown')),
  system_action TEXT NOT NULL,
  operator_decision TEXT NOT NULL
    CHECK (operator_decision IN ('followed', 'deferred', 'overrode')),
  operator_note TEXT NOT NULL DEFAULT '',
  target_type TEXT NOT NULL DEFAULT 'none'
    CHECK (target_type IN ('trade_plan', 'position', 'strategy_proposal', 'paper_acceptance', 'market_review', 'quality', 'none', 'other')),
  target_id INTEGER,
  blocker_codes_json TEXT NOT NULL DEFAULT '[]',
  warning_codes_json TEXT NOT NULL DEFAULT '[]',
  source_refs_json TEXT NOT NULL DEFAULT '[]',
  operator TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (operation_request_id) REFERENCES operation_requests(id),
  FOREIGN KEY (account_id) REFERENCES portfolio_accounts(id)
);

CREATE INDEX IF NOT EXISTS idx_decision_action_logs_account_review
  ON decision_action_logs(account_id, review_date, created_at);

CREATE INDEX IF NOT EXISTS idx_decision_action_logs_execution
  ON decision_action_logs(account_id, execution_date);
