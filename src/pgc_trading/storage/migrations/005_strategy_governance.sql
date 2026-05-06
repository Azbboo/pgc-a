CREATE TABLE IF NOT EXISTS strategy_families (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  family_key TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  description TEXT,
  owner TEXT,
  status TEXT NOT NULL DEFAULT 'researching'
    CHECK (status IN ('researching', 'active', 'paused', 'retired')),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS strategy_versions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  strategy_family_id INTEGER NOT NULL,
  strategy_key TEXT NOT NULL,
  strategy_version TEXT NOT NULL UNIQUE,
  code_version TEXT,
  params_hash TEXT NOT NULL,
  entry_policy_id TEXT,
  exit_policy_id TEXT,
  position_policy_id TEXT,
  agent_policy TEXT NOT NULL DEFAULT 'advisory'
    CHECK (agent_policy IN ('none', 'advisory', 'filter', 'position_sizing')),
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft', 'research', 'candidate', 'paper', 'live_candidate', 'live', 'paused', 'deprecated', 'rejected', 'archived')),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  promoted_at TEXT,
  deprecated_at TEXT,
  FOREIGN KEY (strategy_family_id) REFERENCES strategy_families(id)
);

CREATE INDEX IF NOT EXISTS idx_strategy_versions_status
  ON strategy_versions(status, strategy_key);

CREATE TABLE IF NOT EXISTS parameter_sets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  strategy_version_id INTEGER NOT NULL,
  params_json TEXT NOT NULL,
  params_hash TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (strategy_version_id) REFERENCES strategy_versions(id),
  UNIQUE(strategy_version_id, params_hash)
);

CREATE TABLE IF NOT EXISTS strategy_deployments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  strategy_version_id INTEGER NOT NULL,
  account_id INTEGER NOT NULL,
  deployment_type TEXT NOT NULL
    CHECK (deployment_type IN ('backtest', 'validation', 'paper', 'live')),
  status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('active', 'paused', 'retired')),
  start_date TEXT NOT NULL,
  end_date TEXT,
  max_daily_picks INTEGER NOT NULL DEFAULT 1 CHECK (max_daily_picks >= 0),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  approved_by TEXT,
  FOREIGN KEY (strategy_version_id) REFERENCES strategy_versions(id),
  FOREIGN KEY (account_id) REFERENCES portfolio_accounts(id),
  UNIQUE(strategy_version_id, account_id, deployment_type, start_date)
);
