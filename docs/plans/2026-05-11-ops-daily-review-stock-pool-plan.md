# OPS-20260511 Daily Review And Stock Pool Intake Plan

**Goal:** Run the 2026-05-11 daily review and ingest reviewed new stock pool data without drifting into strategy changes or automatic trading.

**Context:** This is an operational execution session, not a product-development wave. The session may write market data, pool input files, reports, and normal guarded paper daily-review records. It must not enable the production timer, place broker orders, mutate active strategy parameters, or hide missing evidence.

## Inputs The Session Must Confirm

- Review date: `20260511` unless the latest closed trading day resolves differently after market close.
- Account: `paper-main`.
- Operator: use the human-provided operator name, or `azboo` if the user confirms no different operator.
- New stock pool source: ask the user for the new stock list/events if not already present in local files.
- Data source: use existing Tushare cache/fetch scripts and local `.env` token handling; do not hard-code secrets into files or reports.

## Execution Steps

1. Inspect current workspace and remote health.
   - `git status --short`
   - `ssh root@150.158.121.150 "cd /opt/pgc/app && PYTHONPATH=src python3 -m pgc_trading.cli.main ops health --db-path /opt/pgc/data/pgc_trading.db --health-url http://127.0.0.1:8020/api/health --require-current-migrations"`

2. Back up before any apply/import.
   - Local DB backup if touching `data/pgc_trading.db`.
   - Remote DB backup if applying against `/opt/pgc/data/pgc_trading.db`.

3. Refresh/ingest 2026-05-11 market data.
   - Prefer existing scripts such as `scripts/fetch_tushare_market_data.py`.
   - Verify `market_bars`/cached daily files include the review date for all pool and candidate symbols.
   - If 2026-05-11 is not yet a closed trading day, stop at dry-run and document the blocker.

4. Ingest new stock pool data.
   - Update `data/pgc_pool.json` and/or `data/pgc_raw_events.json` using structured JSON, preserving existing format.
   - Do not duplicate existing stock/event entries.
   - Record source/date/reason for each new stock where the schema supports it.
   - Re-run any pool performance or scoring outputs needed by the existing flow.

5. Run dry-run review first.
   - System pipeline:

```bash
./scripts/run_daily_pipeline.sh --date 20260511 --account paper-main --operator azboo --include-market-review --dry-run
```

   - Legacy PGC pool report if needed:

```bash
python3 scripts/run_daily_v2_review.py --date 20260511
```

6. If dry-run is clean, run apply only with operator present.

```bash
./scripts/run_daily_pipeline.sh --date 20260511 --account paper-main --operator azboo --include-market-review --apply
```

7. Verify outputs.
   - `reports/daily_review_20260511.md`
   - `reports/daily_review_20260511.json`
   - `data/daily_review_20260511_*`
   - API: `/api/daily-reviews/20260511?account_key=paper-main`
   - Dashboard can read the date without changing execution date context unexpectedly.

8. Update this ledger entry when done.
   - Mark `OPS-20260511` as `Done` or `Done, Applied`.
   - Include backup path, key report files, selected candidate, next trade plan, evidence blockers, and verification commands.

## Guardrails

- No production timer enablement.
- No broker auto-order.
- No active strategy parameter mutation.
- No market-review POST path from Dashboard.
- Non-dry-run writes require `--operator`.
- Missing data must remain explicit in reports and final summary.

## Acceptance Checklist

- Workspace changes are reviewed and limited to expected data/report/ledger files.
- Dry-run result is captured before apply.
- Apply result, if run, is idempotency-safe and includes backup path.
- New stock pool additions are deduplicated and source-traceable.
- Daily review report and JSON exist for the review date.
- API/Dashboard read path returns the new review.
- Final summary lists selected candidate, tomorrow plan, evidence gaps, and any manual action needed.
