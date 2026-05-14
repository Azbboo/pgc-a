# Remote/Local Parity 20260514

- contract: `remote_local_parity_v1`
- generated_at: `2026-05-14T13:58:44+00:00`
- status: `blocker`
- account_key: `paper-main`
- blockers: `evidence_imports,paper_ledger`
- warnings: `none`

## Endpoint Summary

| Surface | Local | Remote |
| --- | --- | --- |
| Latest migration | `latest_migration=013_decision_action_log` | `latest_migration=013_decision_action_log` |
| Latest market bars | `latest_date=20260514; latest_date_count=263` | `latest_date=20260514; latest_date_count=263` |
| Latest daily review | `latest_db_date=20260513; latest_db_count=1; latest_report_date=20260514` | `latest_db_date=20260513; latest_db_count=1; latest_report_date=20260514` |
| Latest market review | `latest_date=20260514` | `latest_date=20260514` |
| Latest evidence imports | `market_external_latest_date=20260514; market_external_count=4; agent_external_latest_date=20260514; agent_external_count=9` | `market_external_latest_date=20260508; market_external_count=2; agent_external_latest_date=20260508; agent_external_count=3` |
| Paper ledger | `open_positions_count=1; active_trade_plans_count=2` | `open_positions_count=0; active_trade_plans_count=1` |
| Release metadata | `release_tag=pgc-v0.1.0-20260514-m108-m111-plan-r1; git_sha=c8514b3a333e3b31d65cd28f66d0efcc533c5a16` | `release_tag=pgc-v0.1.0-20260514-m108-m111-plan-r1; git_sha=c8514b3a333e3b31d65cd28f66d0efcc533c5a16` |

## Checks

| Check | Status | Detail | Next command |
| --- | --- | --- | --- |
| Database snapshots | `pass` | both database snapshots are readable | none |
| Migration state | `pass` | local and remote values match | none |
| Latest market bars | `pass` | local and remote values match | none |
| Daily review artifacts | `pass` | database daily-review rows and report files match | none |
| Latest market review | `pass` | local and remote values match | none |
| Evidence imports | `blocker` | local and remote values differ | Import reviewed provider files on the stale endpoint, then rerun parity. |
| Paper ledger | `blocker` | local and remote values differ | Pull the production DB after guarded paper-ledger writes, then rerun parity. |
| Release metadata | `pass` | release metadata matches | none |

## Safety

- Read-only parity package; no strategy, trade, paper/live, broker, or timer mutation.
- No live web/provider fetch is performed inside the parity request path.
