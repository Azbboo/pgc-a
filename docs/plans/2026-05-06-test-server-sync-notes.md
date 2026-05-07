# Test Server Sync POC Notes

DEV8 adds a small, optional sync path for derived PGC report artifacts. The
local SQLite database remains the canonical store; test-server MySQL and Redis
are publish targets only.

## Runtime Configuration

Read all connection details from the environment. Keep real values in an
ignored local file such as `.env.test-server`.

```bash
PGC_TEST_MYSQL_HOST=<test-server-host>
PGC_TEST_MYSQL_DATABASE=<test-server-database>
PGC_TEST_MYSQL_USER=<local-only-secret>
PGC_TEST_MYSQL_PASSWORD=<local-only-secret>
PGC_TEST_REDIS_HOST=<test-server-host>
PGC_TEST_REDIS_PORT=6379
PGC_TEST_REDIS_PASSWORD=<local-only-secret-or-empty>
```

Do not commit server passwords, MySQL passwords, Redis passwords, broker
credentials, API tokens, or copied `.env.test-server` contents.

## Dry Run

Dry-run mode validates the environment and report artifact, then prints only
public target details plus the artifact hash.

```bash
PYTHONPATH=/Users/azboo/Desktop/Person/pgc/src \
python3 /Users/azboo/Desktop/Person/pgc/scripts/sync_reports_to_test_server.py \
  --dry-run \
  --report-json /Users/azboo/Desktop/Person/pgc/reports/live_trade_plan.json
```

Expected dry-run behavior:

- exits nonzero with clear instructions when required environment values are
  missing;
- prints MySQL host/database and Redis host/port;
- never prints MySQL or Redis passwords;
- does not call MySQL or Redis clients.

## Real Sync POC

The script supports `--target mysql`, `--target redis`, or the default `both`.
Real sync requires optional local dependencies:

- `pymysql` for MySQL;
- `redis` for Redis.

MySQL receives one idempotent row per `(artifact_type, content_hash)` in
`pgc_report_sync_artifacts`. Redis receives a content-addressed key plus a
latest pointer:

```text
pgc:test-server-sync:daily_report:<sha256>
pgc:test-server-sync:daily_report:latest
```

This POC intentionally does not read from MySQL or Redis when making trading
decisions.

## Test Coverage

`tests/test_test_server_sync_config.py` covers:

- missing required env vars;
- invalid Redis port;
- dry-run redaction and no-client behavior;
- sync behavior with fake MySQL and Redis clients;
- MySQL-only target routing.
