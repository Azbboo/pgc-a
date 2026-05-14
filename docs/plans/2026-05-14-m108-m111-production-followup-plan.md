# M108-M111 Production Follow-Up Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** After the M104-M107 production acceptance release, tighten the next daily operating loop: prove local/remote data parity, make the Dashboard easier to operate during real trading, close 2026-05-14+ evidence gaps with reviewed provider files, and make paper-trading readiness progress visible without changing strategy, broker, or timer behavior automatically.

**Architecture:** Keep the system operator-led. These tasks may add diagnostics, read APIs, reports, provider-file imports, and Dashboard surfaces. They must not auto-place trades, auto-promote shadow strategies, mutate active strategy params, enable timers, or fetch live web evidence inside API/report/trading request paths. Non-dry-run ledger writes still require operator/idempotency safeguards.

**Tech Stack:** Python services/CLI/scripts, SQLite, provider-file evidence packs, Markdown/JSON reports, static Dashboard JavaScript/CSS, pytest/unittest, remote deploy on port `8020`.

---

## Parallel Map

| Lane | Task | Can Run In Parallel | Primary Write Scope | Review Focus |
| --- | --- | --- | --- | --- |
| A | M108 Remote/local data parity and latest evidence reconciliation | Yes | ops parity CLI/service/tests, parity reports | Local and remote DB/report/evidence state match, migration current, no hidden stale data |
| B | M109 Dashboard operator flow polish after production QA | Yes | `web/dashboard/*`, Dashboard static tests, optional QA screenshots | Clear "today/why/next" flow, readable drawers/modals, Chinese-first copy, no overlap |
| C | M110 20260514+ provider evidence closure | Yes | provider-pack files/services/tests/reports | Reviewed-file-only market/Agent evidence, gap QA, no live fetch in request paths |
| D | M111 Paper trading readiness progress loop | Yes | paper acceptance/readiness services/API/report/Dashboard/tests | 10-trade progress, exit lifecycle, blockers and next actions, no auto trade |

## M108: Remote/Local Data Parity And Latest Evidence Reconciliation

**Goal:** Give every child session a trustworthy answer to "which database/report/evidence state is current" after deployment and daily runs.

**Files:**
- Modify or add: ops parity service/CLI under `src/pgc_trading/services/` and `src/pgc_trading/cli/main.py`
- Modify or add: `scripts/*parity*` only if a script is needed for remote collection
- Add artifact: `reports/remote_local_parity_20260514.{json,md}`
- Test: focused ops/CLI tests

**Steps:**
1. Compare local and remote: latest migration, latest market bar date/count, latest daily review date, latest market-review run, latest evidence import dates, paper account positions/plans, and release tag/commit.
2. Surface mismatches as `pass`, `warning`, or `blocker`, with next command hints.
3. Make the command read-only by default and safe to run after deploy.
4. Record 2026-05-14 parity evidence in Markdown/JSON.
5. Verify focused CLI/service tests, `python3 -m compileall -q src scripts`, and `git diff --check`.

## M109: Dashboard Operator Flow Polish After Production QA

**Goal:** Turn the visual-QA-clean Dashboard into an easier live operating surface: less flat scanning, clearer decisions, better modals/drawers.

**Files:**
- Modify: `web/dashboard/app.js`
- Modify: `web/dashboard/styles.css`
- Modify: `web/dashboard/index.html` only if needed
- Test: `tests/test_dashboard_static.py`
- Optional artifact: `reports/dashboard_operator_flow_qa_20260514.md`

**Steps:**
1. Review 开盘执行、每日复盘、全市场复盘、证据/运维、影子策略 for "今天该看什么、为什么不能做、下一步点哪里".
2. Move dense secondary details into consistent drawers/modals where appropriate; keep primary action/status visible on-page.
3. Improve detail drawer design with grouped Chinese sections, source/evidence badges, and clear blockers.
4. Add static checks for important Chinese labels and no raw internal keys in visible copy.
5. Verify `node --check web/dashboard/app.js`, Dashboard static tests, and visual smoke if UI changed materially.

## M110: 20260514+ Provider Evidence Closure

**Goal:** Use reviewed provider files to reduce full-market and TradingAgents evidence gaps for the latest daily review dates.

**Files:**
- Modify: `src/pgc_trading/services/evidence_provider_pack_service.py` only if QA/import gaps remain
- Modify: `src/pgc_trading/services/market_external_data_service.py` or Agent evidence service only if needed
- Add provider artifacts under existing provider/evidence paths
- Refresh: relevant `reports/daily_review_*.{json,md}` and evidence QA artifacts
- Test: evidence provider pack tests and report tests

**Steps:**
1. Generate or validate 2026-05-14+ provider-pack manifests for market sector/news/sentiment and Agent fundamentals/news/sentiment/announcement sections.
2. Import only reviewed provider files; rejected, stale, unavailable, and missing sources must remain explicit.
3. Refresh daily review and full-market narrative outputs so the page no longer appears empty when evidence exists.
4. Keep no-live-fetch guarantees in trading/report/API request paths.
5. Verify focused evidence/report tests, compile, and `git diff --check`.

## M111: Paper Trading Readiness Progress Loop

**Goal:** Make paper readiness operationally useful: show exactly how far the account is from the 10-completed-trade gate, which exits are due, and what manual action comes next.

**Files:**
- Modify: paper acceptance/readiness service and read API if needed
- Modify: daily report renderer if readiness summary is missing
- Modify: Dashboard paper/execution sections if needed
- Test: paper acceptance, portfolio, API, Dashboard static tests

**Steps:**
1. Normalize readiness progress: completed trades, open positions, waiting T+2/T+5, overdue exits, unresolved blockers, latest Agent/evidence status.
2. Add a concise next-action summary for manual operators, without creating new trade plans or placing orders.
3. Make "not ready because X" and "ready after Y" visible in Dashboard and daily report.
4. Add regressions proving no broker/paper-live/timer writes and no automatic strategy promotion.
5. Verify focused paper/API/Dashboard tests, full suite if shared behavior changes, and `git diff --check`.

## Integration Gate

After M108-M111 complete:

1. Run focused checks:
   - `node --check web/dashboard/app.js`
   - `python3 -m compileall -q src scripts`
   - focused pytest for changed services/API/Dashboard/report paths
2. Run full suite:
   - `PYTHONPATH=src:. pytest -q`
3. Update `docs/plans/global-task-ledger.md` in the same branch, marking completed tasks and release anchors.
4. Commit, push, deploy, then run remote health:
   - `bash scripts/deploy_remote.sh --release-tag pgc-v0.1.0-20260514-m108-m111-production-followup-r1`
   - `ssh root@150.158.121.150 "cd /opt/pgc/app && PYTHONPATH=src python3 -m pgc_trading.cli.main ops health --db-path /opt/pgc/data/pgc_trading.db --health-url http://127.0.0.1:8020/api/health --require-current-migrations"`

