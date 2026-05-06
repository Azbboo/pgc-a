CREATE TABLE IF NOT EXISTS input_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  snapshot_type TEXT NOT NULL,
  as_of_date TEXT NOT NULL,
  signal_id INTEGER,
  daily_pick_id INTEGER,
  source_refs_json TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (signal_id) REFERENCES strategy_signals(id),
  FOREIGN KEY (daily_pick_id) REFERENCES daily_picks(id),
  UNIQUE(snapshot_type, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_input_snapshots_signal
  ON input_snapshots(signal_id);

CREATE TABLE IF NOT EXISTS agent_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  agent_system TEXT NOT NULL,
  agent_version TEXT,
  signal_id INTEGER,
  daily_pick_id INTEGER,
  input_snapshot_id INTEGER NOT NULL,
  as_of_date TEXT NOT NULL,
  config_json TEXT NOT NULL,
  config_hash TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'planned'
    CHECK (status IN ('planned', 'running', 'completed', 'failed', 'skipped')),
  started_at TEXT,
  finished_at TEXT,
  error_message TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (signal_id) REFERENCES strategy_signals(id),
  FOREIGN KEY (daily_pick_id) REFERENCES daily_picks(id),
  FOREIGN KEY (input_snapshot_id) REFERENCES input_snapshots(id)
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_signal
  ON agent_runs(signal_id);

CREATE INDEX IF NOT EXISTS idx_agent_runs_as_of_date
  ON agent_runs(as_of_date);

CREATE TABLE IF NOT EXISTS agent_artifacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  agent_run_id INTEGER NOT NULL,
  artifact_type TEXT NOT NULL
    CHECK (artifact_type IN ('raw_state', 'final_report', 'debug_log', 'memory_delta', 'tool_trace', 'decision_json')),
  path TEXT NOT NULL,
  content_hash TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (agent_run_id) REFERENCES agent_runs(id),
  UNIQUE(agent_run_id, artifact_type, path)
);

CREATE TABLE IF NOT EXISTS agent_decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  agent_run_id INTEGER NOT NULL,
  signal_id INTEGER,
  daily_pick_id INTEGER,
  action TEXT NOT NULL DEFAULT 'no_opinion'
    CHECK (action IN ('support', 'caution', 'reject', 'review_required', 'no_opinion')),
  confidence REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  risk_level TEXT NOT NULL DEFAULT 'unknown'
    CHECK (risk_level IN ('low', 'medium', 'high', 'unknown')),
  summary TEXT,
  supporting_points_json TEXT,
  risk_points_json TEXT,
  raw_decision_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (agent_run_id) REFERENCES agent_runs(id),
  FOREIGN KEY (signal_id) REFERENCES strategy_signals(id),
  FOREIGN KEY (daily_pick_id) REFERENCES daily_picks(id),
  UNIQUE(agent_run_id)
);
