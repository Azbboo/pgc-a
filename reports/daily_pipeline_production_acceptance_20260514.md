# M105 Daily Pipeline Production Acceptance - 20260514

## Scope

M105 validates the latest daily-data and stock-pool production runbook without forcing writes when the latest trading day is not locally ready.

## Latest-Day Readiness And Apply

Initial readiness was blocked before market refresh, then market data was populated and the guarded daily pipeline was applied.

- Initial dry-run command: `PGC_DAILY_PIPELINE_NOW_DATE=20260514 PGC_DAILY_PIPELINE_NOW_TIME=153100 ./scripts/run_daily_pipeline.sh --date latest-closed --account paper-main --operator azboo --db-path data/pgc_trading.db --include-market-review --dry-run`
- Initial result: blocked before pipeline writes because `market data missing for resolved_date=20260514`.
- Final apply command: `./scripts/run_daily_pipeline.sh --date 20260514 --account paper-main --operator azboo --db-path data/pgc_trading.db --include-market-review --pool-intake-summary data/daily_review_20260514_intake_apply.json --apply`
- Final result: pass.
- Evidence log: `.pgc-runs/daily-pipeline-20260514.log`
- Key fields:
  - `duplicate_apply_count=0`
  - `duplicate_write_guard=pass`
  - `daily_preflight_status=pass`
  - `pool_intake_status=available`
  - `pool_intake_mode=apply`
  - `pool_intake_input_count=6`
  - `pool_intake_added_count=6`
  - `pool_intake_rejected_count=0`
  - `daily_step=market_data status=pass count=263`
  - `pipeline_status=pass`
  - `daily_operating_state=apply_complete`
  - `market_review_status=success`
  - `report_status=success`
  - `backup_path=data/backups/pgc_trading_20260514_185518_998714_before_daily_pipeline_20260514.db`
  - `report_markdown=reports/daily_review_20260514.md`
  - `report_json=reports/daily_review_20260514.json`

## Post-Apply Dry-Run Review

- Command: `./scripts/run_daily_pipeline.sh --date 20260513 --account paper-main --operator azboo --db-path data/pgc_trading.db --include-market-review --pool-intake-summary data/daily_review_20260513_intake_apply.json --require-pool-intake --dry-run --evidence-run m105-post-apply-review`
- Result: pass.
- Evidence log: `.pgc-runs/daily-pipeline-20260513-m105-post-apply-review.log`
- Key fields:
  - `duplicate_apply_count=3`
  - `duplicate_write_guard=dry_run`
  - `post_apply_review=dry_run_allowed`
  - `daily_preflight_status=pass`
  - `missing_steps=none`
  - `pool_intake_status=available`
  - `pool_intake_mode=apply`
  - `pool_intake_input_count=6`
  - `pool_intake_added_count=6`
  - `pool_intake_rejected_count=0`
  - `pool_intake_dedupe_count=0`
  - `pipeline_status=pass`
  - `daily_operating_state=dry_run_ready`
  - `write_intent=dry_run_no_writes`
  - `backup_path=none`
  - `changed=false`

## Verification

- `bash -n scripts/run_daily_pipeline.sh`
- `python3 -m compileall -q src/pgc_trading/ops.py src/pgc_trading/cli/main.py src/pgc_trading/services/daily_pipeline_service.py`
- `PYTHONPATH=src:. pytest tests/test_daily_pipeline_script.py tests/test_daily_pipeline_service.py tests/test_cli_daily_pipeline.py tests/test_operational_runbook_static.py tests/test_cli_main.py` (`87 passed`)

## Safety

- `20260514` apply was run only after market data and pool intake preflight passed.
- Database backup was created before apply.
- Post-apply review was dry-run only.
- No timer, broker, active strategy parameter, trade, or position mutation was requested.
