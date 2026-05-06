CREATE TABLE IF NOT EXISTS data_quality_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  layer TEXT NOT NULL
    CHECK (layer IN ('raw', 'market', 'feature', 'signal', 'agent', 'portfolio', 'report')),
  severity TEXT NOT NULL
    CHECK (severity IN ('info', 'warning', 'error', 'blocker')),
  event_code TEXT NOT NULL,
  entity_type TEXT,
  entity_id INTEGER,
  ts_code TEXT,
  trade_date TEXT,
  message TEXT NOT NULL,
  payload_json TEXT,
  status TEXT NOT NULL DEFAULT 'open'
    CHECK (status IN ('open', 'acknowledged', 'resolved', 'ignored')),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_data_quality_status
  ON data_quality_events(status, severity, layer);
