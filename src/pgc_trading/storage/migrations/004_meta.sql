CREATE TABLE IF NOT EXISTS operation_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  idempotency_key TEXT NOT NULL UNIQUE,
  request_id TEXT,
  operation_type TEXT NOT NULL,
  account_id INTEGER,
  as_of_date TEXT,
  status TEXT NOT NULL DEFAULT 'started'
    CHECK (status IN ('started', 'success', 'partial_success', 'skipped', 'failed')),
  request_json TEXT NOT NULL,
  response_json TEXT,
  error_code TEXT,
  error_message TEXT,
  operator TEXT,
  started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finished_at TEXT,
  FOREIGN KEY (account_id) REFERENCES portfolio_accounts(id)
);

CREATE INDEX IF NOT EXISTS idx_operation_requests_type_date
  ON operation_requests(operation_type, as_of_date);

CREATE TABLE IF NOT EXISTS domain_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_type TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id INTEGER NOT NULL,
  account_id INTEGER,
  occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  payload_json TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'system'
    CHECK (source IN ('system', 'manual', 'scheduler', 'broker_import', 'migration')),
  operator TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (account_id) REFERENCES portfolio_accounts(id)
);

CREATE INDEX IF NOT EXISTS idx_domain_events_entity
  ON domain_events(entity_type, entity_id);

CREATE INDEX IF NOT EXISTS idx_domain_events_account_time
  ON domain_events(account_id, occurred_at);
