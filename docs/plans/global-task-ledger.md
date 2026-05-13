# Global Task Ledger

Last updated: 2026-05-13

This ledger is the single index for historical and active project work. Detailed specs remain in the linked plan and design documents; this file tracks the global status, release anchors, and next dependencies.

## Current Release State

| Field | Value |
| --- | --- |
| Branch | `codex/m96-shadow-walk-forward-outcomes` |
| Latest deployed commit | See release tag `pgc-v0.1.0-20260513-m91-m94-r2` |
| Latest release tag | `pgc-v0.1.0-20260513-m91-m94-r2` |
| Remote API | `http://150.158.121.150:8020` |
| Remote migration state | `013_decision_action_log`, `pending_migrations=none` |
| Latest release health | `api_health_ok=true`, HTTP `200` |
| Latest full verification | `472 passed, 3 skipped, 10 subtests passed` locally on 2026-05-13 after M95-M99 local implementation. Focused M95-M99 checks passed (`103 passed, 1 skipped`), `node --check web/dashboard/app.js`, Python compile checks, `git diff --check`, and direct Dashboard Chinese-first static checks passed (`30 passed, 1 skipped`). M98/M99 remain read-only for strategy/trade/paper-live/timer boundaries. |

## Status Legend

| Status | Meaning |
| --- | --- |
| Done | Implemented, reviewed, and accepted for the current project baseline. |
| Deployed | Done and included in a server deployment. |
| Next | Ready to start or already assigned to a future session. |
| In Review | Implementation exists but still needs Codex review or integration checks. |
| Blocked | Needs an upstream dependency or decision. |
| Superseded | Earlier planning artifact replaced by a later task or release flow. |

## Canonical Sources

| Scope | Source |
| --- | --- |
| Early roadmap M0-M10 | `reports/development_implementation_roadmap.md` |
| Detailed early tickets | `reports/implementation_ticket_breakdown_design.md` |
| DEV0-DEV16 supervision | `docs/plans/2026-05-06-pgc-development-supervision-plan.md` |
| M10 paper/live readiness | `docs/plans/2026-05-07-m10-paper-live-readiness-plan.md` |
| M15 live ops and Agent review | `docs/plans/2026-05-08-m15-live-ops-agent-review-plan.md` |
| M24-M28 ops/dashboard wave | `docs/plans/2026-05-09-m24-m28-next-stage-plan.md` |
| M28-M34 operating loop wave | `docs/plans/2026-05-09-m28-m34-operating-loop-plan.md` |
| M35-M42 market review strategy wave | `docs/plans/2026-05-09-m35-m42-market-review-strategy-evolution-plan.md` |
| M39-M46 integration wave | `docs/plans/2026-05-09-m39-m46-market-review-integration-plan.md` |
| M47-M52 market intelligence next wave | `docs/plans/2026-05-09-m47-m52-market-intelligence-next-wave-plan.md` |
| M51-M54 release, timeline, and ops wave | `docs/plans/2026-05-09-m51-m54-release-timeline-ops-plan.md` |
| M55-M58 paper intelligence ops wave | `docs/plans/2026-05-10-m55-m58-paper-intelligence-ops-plan.md` |
| M59-M62 paper ops evidence and strategy wave | `docs/plans/2026-05-10-m59-m62-paper-ops-evidence-strategy-plan.md` |
| M63-M66 evidence, proposal, ops, and decision wave | `docs/plans/2026-05-10-m63-m66-paper-decision-quality-plan.md` |
| M67-M70 pool, evidence, strategy, and decision follow-up | `docs/plans/2026-05-11-m67-m70-pool-evidence-strategy-followup-plan.md` |
| M71-M74 market intelligence operationalization | `docs/plans/2026-05-12-m71-m74-market-intelligence-operationalization-plan.md` |
| M75-M78 market intelligence daily ops | `docs/plans/2026-05-12-m75-m78-market-intelligence-daily-ops-plan.md` |
| M79-M82 shadow strategy visibility | `docs/plans/2026-05-12-m79-m82-shadow-strategy-visibility-plan.md` |
| M83-M86 shadow observation loop | `docs/plans/2026-05-13-m83-m86-shadow-observation-loop-plan.md` |
| M87-M90 shadow observation operations | `docs/plans/2026-05-13-m87-m90-shadow-observation-operations-plan.md` |
| M91-M94 shadow promotion evidence | `docs/plans/2026-05-13-m91-m94-shadow-promotion-evidence-plan.md` |
| M95-M98 shadow evidence to decision loop | `docs/plans/2026-05-13-m95-m98-shadow-decision-loop-plan.md` |
| External stock project integration assessment | `docs/plans/2026-05-12-stock-instock-integration-plan.md` |
| OPS-20260511 daily review and stock pool intake | `docs/plans/2026-05-11-ops-daily-review-stock-pool-plan.md` |

## DEV Work Packages

| Task ID | Name | Status | Primary Output | Notes |
| --- | --- | --- | --- | --- |
| DEV0 | Baseline Commit & Tracking | Done | Clean baseline commit and status board | Historical supervision board. |
| DEV1 | CLI Command Skeleton | Done | `pgc` command entrypoints | Foundation for later CLI tasks. |
| DEV2A | CPB V2 Strategy Integration | Done | `cpb_v2@2026-05-06` candidate | Strategy service dispatch ready. |
| DEV2 | DailyCloseWorkflowService | Done | One-call daily close orchestration | Basis for daily-close pipeline. |
| DEV3 | Daily Review Report Output | Done | Markdown/JSON daily report | Daily review report path. |
| DEV4 | Tushare Runtime Adapter Hardening | Done | Env-driven real fetch guardrails | Production data guardrails. |
| DEV5 | Execution Recording CLI | Done | Record buy/sell execution safely | Paper/live ledger path. |
| DEV6 | Position Exit Decision CLI | Done | T+2/T+5 review commands | Exit lifecycle support. |
| DEV7 | Replay & Golden Regression | Done | No-future replay gate | Regression and no-future checks. |
| DEV8 | Test Server Sync POC | Done | Optional MySQL/Redis sync | No secrets committed. |
| DEV9 | HTTP API P0 | Done | Service-backed API | Includes DEV9A/B/C follow-up work. |
| DEV10 | Dashboard P0 | Done | Production Dashboard baseline | Later improved by M17/M27/M41B. |
| DEV11 | M10 Account Catalog | Done | `paper-main`/`live-main` readiness | Account defaults aligned. |
| DEV12 | M10 Paper Smoke | Done | Daily-close apply smoke | Paper workflow baseline. |
| DEV13 | M10 Paper Readiness | Done | Paper acceptance gate | Promotion/readiness checks. |
| DEV14 | M10 Live Dry Run | Done | `live-main` dry-run only | No live apply without explicit gate. |
| DEV15 | M10 Runbook Final Gate | Done | Repeatable M10 operations | Operational documentation. |
| DEV16 | M11 Real Execution Loop | Done | Explicit live ledger execution loop | Live ledger writes only, no broker auto-order. |

## Milestone Ledger

| Task ID | Name | Status | Release / Commit Anchor | Verification / Notes |
| --- | --- | --- | --- | --- |
| M0 | Code inventory and migration baseline | Done | Early baseline docs | See `reports/implementation_baseline_20260504.md`. |
| M1 | Target database and migrations | Done | Migration stack `001`-`009` | Schema runner, seed data, invariant direction. |
| M2 | Data service and quality gate | Done | Raw/market/data quality services | Tushare production path and guards. |
| M3 | Strategy service and daily review | Done | Strategy/daily review services | Daily pick and report generation. |
| M4 | Portfolio planning, trades, positions, exits | Done | Portfolio lifecycle services | Paper ledger state machine. |
| M5 | Tests, replay, golden gates | Done | Replay test suite | No-future and account boundary checks. |
| M6 | TradingAgents advisory bridge | Done | Agent review service | Advisory only; no trade mutation. |
| M7 | CLI full loop | Done | CLI commands | Daily close, execution, exit commands. |
| M8 | HTTP API | Done | API routes | Read and guarded write entrypoints. |
| M9 | Dashboard P0 | Done | Dashboard P0 | First production operator surface. |
| M10 | Paper operation and live readiness | Done | DEV11-DEV15 | Includes account catalog, paper smoke, readiness, live dry-run, runbook gate. |
| M11 | Real execution loop | Done | DEV16 | Live ledger write guards, no broker auto-order. |
| M12 | Daily review history / workflow follow-up | Done | User reported complete | Included in later report/history work. |
| M13 | yfinance isolation and price correctness follow-up | Done | User reported complete | yfinance kept diagnostic and isolated. |
| M14A | Review/history workflow cleanup | Done | User reported complete | Historical review navigation foundation. |
| M14B | yfinance diagnostic provider | Done | `015566f` and follow-ups | Isolated `market_diagnostic_bars`, not production `market_bars`. |
| M14C | Agent external data enrichment | Done | `015566f` and follow-ups | Cached external context for Agent snapshots only. |
| M15 | Live ops, Agent review, and report integration | Done | `9cc5292` plus later fixes | Agent output/report surfaced and localized. |
| M16 | End-of-day data loop | Done | `3914c30` | Daily close loop and report refresh. |
| M17 | Dashboard operation flow optimization | Done | `6180a1f` and related commits | Detail drawer and operation flow improvements. |
| M20 | Deployment ops standardization | Done | `3914c30`, `3ff703e` | Deploy script, migration, backup, health, release tag flow. |
| M21 | Redone after drift | Done | User reported complete | Original M21 paused and redone. |
| M22 | Open execution closure and interaction fix | Done | `58f8fd6`, `f96c7fc` | 2026-05-08 buy ledger fixed and report refreshed. |
| M23 | End-of-day automatic pipeline script | Done | User reported complete | Standard daily pipeline work continued in M25/M42. |
| M24 | Ledger consistency and repair guardrails | Done, Deployed | `23b6468` | Ledger audit/repair and invariant expansion. |
| M25 | First-class daily pipeline | Done, Deployed | `23b6468` | Pipeline command/script and idempotency path. |
| M26 | TradingAgents evidence coverage | Done, Deployed | `23b6468` | External evidence coverage surfaced. |
| M27 | Dashboard modal and daily task clarity | Done, Deployed | `23b6468` | Modal/confirmation flow and task clarity. |
| M28 | Ops acceptance and runbook refresh | Done, Deployed | `9f853c2` | Acceptance gates and runbook refresh. |
| M32 | Agent evidence / readiness follow-up | Done, Deployed | `9f853c2` | Included in ops safety and Agent evidence release. |
| M33 | Readiness / schema follow-up | Done, Deployed | `9f853c2` | Included in market schema/readiness release. |
| M34 | Market schema follow-up | Done, Deployed | `9f853c2` | Included in `012_market_review` schema wave. |
| M35 | Full-market review strategy planning | Done, Deployed | `9f853c2` | Strategy hypothesis direction established. |
| M36 | Market review regime producer | Done, Deployed | `62d1b33` | `market-review run` dry-run works for 20260508. |
| M37 | Sector rotation / external evidence producer | Done, Deployed | `62d1b33` | Market review supporting services. |
| M38 | Market review service integration | Done, Deployed | `62d1b33` | Analysis producers connected. |
| M39 | Plan-context linking | Done, Deployed | `8e3a36f`, release `pgc-v0.1.0-20260509-g8e3a36f` | Writes only `market_plan_contexts`; no trade mutation. |
| M40 | Strategy hypotheses | Done, Deployed | `62d1b33` | Hypotheses generated from market-review observations. |
| R0 | Release checkpoint for M28-M40 | Done, Deployed | `3ff703e` | Optional deploy write token handling, remote migration state preserved. |
| M41A | Market review read API | Done, Deployed | `8e3a36f`, release `pgc-v0.1.0-20260509-g8e3a36f` | GET-only `/api/market-reviews...` routes. |
| M41B | Dashboard full-market tab | Done, Deployed | release `pgc-v0.1.0-20260509-m41b-m46` | Adds read-only full-market Dashboard tab over `market-reviews` APIs; no market-review write calls. |
| M42 | Daily pipeline market-review integration | Done, Deployed | release `pgc-v0.1.0-20260509-m41b-m46` | `daily-pipeline` and `run_daily_pipeline.sh` support `--include-market-review`; dry-run preserves no-write contract. |
| M43 | Production market-review data source policy | Done, Deployed | `8e3a36f`, release `pgc-v0.1.0-20260509-g8e3a36f` | Fixtures forbidden in production; missing evidence explicit. |
| M44 | Strategy hypothesis backtest bridge | Done, Deployed | `8e3a36f`, release `pgc-v0.1.0-20260509-g8e3a36f` | Produces backtest request artifacts; no active param mutation. |
| M45 | Open execution alignment with market-plan context | Done, Deployed | release `pgc-v0.1.0-20260509-m41b-m46` | Added read-only open-execution service/API/CLI/Dashboard context; shows alignment/risk/action and does not auto-cancel or execute trades. |
| M46 | Scheduled post-close pipeline | Done, Deployed | release `pgc-v0.1.0-20260509-m41b-m46` | `latest-closed`, `/opt/pgc/logs`, `/opt/pgc/backups`, health precheck, and systemd timer installer added; remote timer preview passed but timer is not enabled yet. |
| M47 | Data evidence closed loop | Done, Deployed | `159382f`, release `pgc-v0.1.0-20260509-m47-m50` | Provider-tagged market/sector/stock news, sentiment, policy, and research evidence with freshness/coverage states; no live web fetch in trading path. |
| M48 | Full-market Dashboard interaction upgrade | Done, Deployed | `159382f`, release `pgc-v0.1.0-20260509-m47-m50` | Cross-day selector, history strip, sector/evidence drawers, source metadata, and plan relationship view added; verified with Dashboard/API static tests and full suite. |
| M49 | TradingAgents Chinese structured report | Done, Deployed | `159382f`, release `pgc-v0.1.0-20260509-m47-m50` | Chinese source-labeled TradingAgents sections for fundamentals, news, sentiment, technicals, sector context, risks, conclusion, raw artifacts, and unavailable fallback. |
| M50 | Strategy evolution validation loop | Done, Deployed | `159382f`, release `pgc-v0.1.0-20260509-m47-m50` | Hypothesis evidence/backtest gates before acceptance; accepted hypotheses create future strategy-version tasks only. |
| M51 | Review timeline and cross-day comparison | Done, Deployed | release `pgc-v0.1.0-20260510-m51-m54` | Added `/api/review-timeline`, Dashboard cross-day comparison, and locked opening execution-date context while review-date navigation changes. |
| M52 | Scheduled pipeline activation and ops monitor | Done, Deployed | release `pgc-v0.1.0-20260510-m51-m54` | Timer installer defaults to preview, real activation requires `--enable`, `--status` reports health/journal/rollback context, and `run_daily_pipeline.sh` blocks duplicate apply writes unless `--allow-rerun`; remote monitor confirmed timer `not-found`/`inactive`. |
| M53 | Release M47-M50 checkpoint | Done, Deployed | release `pgc-v0.1.0-20260509-m47-m50` | Deployed `d34d2d198c3c8479721fb686687f6ed13818deac`; remote health HTTP `200`, migration `012_market_review`, `pending_migrations=none`; timer remained `not-found`/`inactive`. |
| M54 | Production evidence import operations | Done, Deployed | release `pgc-v0.1.0-20260510-m51-m54` | Added provider-file contracts for market/Agent evidence, dry-run coverage summaries, stale/duplicate/missing counts, and source-hash mismatch guards. |
| M55 | Historical evidence backfill and coverage QA | Done, Deployed | release `pgc-v0.1.0-20260510-m55-m58` | Added historical market/Agent evidence backfill with cross-date `coverage_qa_json`, all-or-nothing validation before apply, CLI commands, and runbook coverage QA. |
| M56 | Strategy hypothesis evaluation workbench | Done, Deployed | release `pgc-v0.1.0-20260510-m55-m58` | Added read-only strategy hypothesis workbench, evidence/backtest artifact acceptance gates, and safety payloads without mutating strategy params or paper/live behavior. |
| M57 | Paper trading operations acceptance dashboard | Done, Deployed | release `pgc-v0.1.0-20260510-m55-m58` | Added paper acceptance API/report/Dashboard view for freshness, evidence coverage, Agent status, open-execution state, readiness gates, and blockers. |
| M58 | Timer enablement decision and safe activation | Done, Deployed | release `pgc-v0.1.0-20260510-m55-m58` | Local activation gate now requires `--approval-id` plus three dry-run evidence logs; production timer remains disabled until operator approval; rollback and duplicate-write guard tested. |
| M59 | Production evidence backfill execution | Done, Deployed | release `pgc-v0.1.0-20260510-m59-m62` | Backed up remote DB to `/opt/pgc/backups/pgc_trading-20260510-193204.db`; generated cached provider files for `20260507`/`20260508`; inserted 4 market and 6 Agent evidence rows; refreshed market-review runs/reports; QA blockers for missing sector and Agent announcement/news/sentiment remain explicit. |
| M60 | Strategy-version proposal workflow | Done, Deployed | release `pgc-v0.1.0-20260510-m59-m62` | Added `strategy-evolution proposal` JSON artifacts from accepted hypotheses; verification: `node --check web/dashboard/app.js`, targeted M60 pytest, full `PYTHONPATH=src:. pytest -q`, and `git diff --check`. |
| M61 | Paper acceptance history and alerting | Done, Deployed | release `pgc-v0.1.0-20260510-m59-m62` | Added read-only paper acceptance history API/Dashboard trend, alert list for unresolved blockers, stale evidence, missing Agent review, and open-execution mismatch; no trade execution or plan cancellation writes. |
| M62 | Timer dry-run evidence collection | Done, Deployed | release `pgc-v0.1.0-20260510-m59-m62` | Added numbered dry-run evidence logs and remote collect action; 2026-05-10 remote dry-run passed but had `duplicate_apply_count=2` for `20260508`, so three M58-ready `duplicate_apply_count=0` logs remain pending and timer stays disabled. |
| M63 | Evidence blocker closure for sector/news/sentiment | Done, Deployed | release `pgc-v0.1.0-20260511-m63-m66` | Added reviewed `unavailable_sources` provider-file states for market sector and Agent announcement/news/sentiment gaps, import/backfill QA gap summaries, CLI `evidence_gap_json`, and daily-report explicit missing/partial/unavailable evidence coverage. |
| M64 | Strategy proposal review and promotion gate | Done, Deployed | release `pgc-v0.1.0-20260511-m63-m66` | Added proposal review and promotion-request artifact workflow, API route, Dashboard controls, workbench review counts, and safety checks; proposal/promotion artifacts do not mutate strategy versions or trading state. |
| M65 | Ops run history and evidence observability | Done, Deployed | release `pgc-v0.1.0-20260511-m63-m66` | Added read-only `/api/ops-history` and Dashboard 运维历史 over operation requests, pipeline/evidence logs, backups, release artifacts, health evidence, paper acceptance snapshots, and timer action evidence; scripts now emit `ops_history_*` fields without enabling timers or rerunning apply jobs. |
| M66 | Next-trading-day decision cockpit | Done, Deployed | release `pgc-v0.1.0-20260511-m63-m66` | Added read-only next-day decision cockpit in report/API/Dashboard, combining market review, evidence blockers, paper acceptance, open execution, and strategy proposals into one manual action checklist. |
| M67 | Stock pool intake validator and audit trail | Done, Deployed | release `pgc-v0.1.0-20260512-m67-m70` | Added structured stock-pool intake validation/dedupe/audit summaries for `pgc_pool.json` and `pgc_raw_events.json`, requiring source/reason/event date before apply and preserving existing JSON shapes. |
| M68 | Evidence provider pack automation | Done, Deployed | release `pgc-v0.1.0-20260512-m67-m70` | Added ops-only provider-file pack flow for sector/news/sentiment/announcement evidence so M63 unavailable states can be closed without live fetches in trading paths. |
| M69 | Strategy promotion shadow evaluation | Done, Deployed | release `pgc-v0.1.0-20260512-m67-m70` | Added research-only shadow evaluation reports/scripts for missed movers, trend-extension, breakout-pressure, low-price momentum, pre-confirm watchlist, and pullback dip-buy hypotheses; no active params, trade plans, trades, positions, paper/live behavior, or timers changed. |
| M70 | Decision cockpit action log and review loop | Done, Deployed | release `pgc-v0.1.0-20260512-m67-m70` | Added advisory cockpit follow/defer/override action logs with next-day outcome review, API/report/Dashboard surfaces, migration `013_decision_action_log`, and explicit no trade/state/timer mutation safety flags. |
| M71 | Evidence pack execution and 20260511 external coverage closure | Done, Deployed | release `pgc-v0.1.0-20260512-m71-m74` | Executed reviewed `evidence_provider_pack_v1` for `20260511`, applied 4 market rows and 6 Agent cached rows from copied pack files, re-rendered daily reports, and left announcement/news/sentiment gaps explicit without live fetches or fabricated evidence. |
| M72 | Market review data sync and empty-state diagnostics | Done, Deployed | release `pgc-v0.1.0-20260512-m71-m74` | Added market-review detail diagnostics, Dashboard empty-state/root-cause strip, read-only local/remote parity ops check, and runbook coverage. Verified with `node --check web/dashboard/app.js`, targeted M72 pytest, full `PYTHONPATH=src:. pytest -q`, and `git diff --check`. |
| M73 | Shadow strategy promotion workbench | Done, Deployed | release `pgc-v0.1.0-20260512-m71-m74` | Added `strategy-evolution register-shadow` and workbench shadow comparison gates for trend-extension, breakout-pressure, low-price momentum, pre-confirm watchlist, and dip-buy candidates; Codex review restored active CPB `min_entry_price=10.0`/params hash and added regression coverage so candidates remain artifact-only. |
| M74 | Decision action outcome review and ops audit hardening | Done, Deployed | release `pgc-v0.1.0-20260512-m71-m74` | Added normalized action-log outcome buckets/counts, stricter execution-date trade matching, unexpected-trade audit detection, ops-history action-log details, and Dashboard outcome drill-down while preserving advisory-only/no trade-state/no timer boundaries. Verification: `node --check web/dashboard/app.js`, targeted M74 pytest, full `PYTHONPATH=src:. pytest -q` (`407 passed, 3 skipped, 10 subtests passed`), and `git diff --check`. |
| M75 | Daily review and stock-pool intake closure for 20260512+ | Done, Deployed | release `pgc-v0.1.0-20260513-m75-m82-r1` | Added `ops daily-preflight` read-only apply checklist, 20260512+ runbook closure for pool intake -> market refresh -> preflight -> dry-run/apply, and duplicate apply detection. Local 20260512 preflight correctly blocks rerun with `duplicate_apply_count=2`; no timer, trade, strategy, or broker writes were enabled. |
| M76 | Full-market review hierarchy and plan linkage UX | Done, Deployed | release `pgc-v0.1.0-20260513-m75-m82-r1` | Added read-only hierarchy payload and Dashboard/report UX for market regime -> sector -> representative stocks -> evidence freshness/source_refs -> continuity -> next-day plan relationship, with aligned/cautious/blocked/missing labels and explicit missing evidence states. Verification: `node --check web/dashboard/app.js`, targeted M76 pytest, full `PYTHONPATH=src:. pytest -q`, and `git diff --check`. |
| M77 | External evidence provider QA and coverage ledger | Done, Deployed | release `pgc-v0.1.0-20260513-m75-m82-r1` | Added read-only evidence coverage ledger service, `ops evidence-ledger`, `/api/evidence-coverage-ledger`, and daily report JSON/Markdown summary; compares provider-pack manifest rows with imported market/Agent evidence and surfaces stale/missing/unavailable/partial/duplicate/source-hash-mismatch states without live fetches or trading writes. Verification: targeted M77 pytest `42 passed`, full `PYTHONPATH=src:. pytest -q` (`420 passed, 3 skipped, 10 subtests passed`), and `git diff --check`. |
| M78 | Shadow strategy monitor and promotion preflight | Done, Deployed | release `pgc-v0.1.0-20260513-m75-m82-r1` | Added artifact-only shadow monitor/preflight outputs for 5 candidate lanes, 20-trading-day walk-forward progress, frozen CPB comparison, API-ready JSON summary, and regression coverage proving no strategy/trade/position/paper-live/timer mutation. |
| M79 | Shadow snapshot feed and API contract | Done, Deployed | release `pgc-v0.1.0-20260513-m75-m82-r1` | Added `shadow_strategy_snapshot_v1` read-only feed over latest shadow monitor/preflight artifacts plus artifact-only strategy hypothesis rows, with `/api/shadow-strategy-snapshot`, `ops shadow-snapshot`, blocker/family/walk-forward/frozen-CPB normalization, embedded artifact path normalization, and explicit no strategy/trade/paper-live/timer write safety. Verification: targeted M79 pytest `33 passed`, CLI/API focused set `71 passed, 1 subtests passed`, full `PYTHONPATH=src:. pytest -q` (`425 passed, 3 skipped, 10 subtests passed`). |
| M80 | Dashboard shadow lab view | Done, Deployed | release `pgc-v0.1.0-20260513-m75-m82-r1` | Added read-only Dashboard Shadow Lab over `/api/shadow-strategy-snapshot` with candidate family counts, walk-forward progress, promotion blocker totals, frozen-CPB comparison, safety boundary metrics, candidate detail drawer, and M82 cache-bust assets. Verification: `node --check web/dashboard/app.js`; `PYTHONPATH=src:. pytest -q tests/test_dashboard_static.py tests/test_api_read_routes.py`. |
| M81 | Daily report and CLI shadow summary | Done, Deployed | release `pgc-v0.1.0-20260513-m75-m82-r1` | Added `shadow_strategy` to daily review JSON/Markdown plus compact `ops shadow-snapshot --compact` summary lines for latest monitor/preflight dates, candidate/blocker counts, top candidates, and artifact-only safety; refreshed `reports/daily_review_20260512.*` and `reports/daily_review_20260513.*`. Verification: focused report/CLI pytest (`52 passed, 1 subtests passed`) and full `PYTHONPATH=src:. pytest -q` (`428 passed, 3 skipped, 10 subtests passed`). |
| M82 | Guardrails, tests, and release gate | Done, Deployed | release `pgc-v0.1.0-20260513-m75-m82-r1` | Added mutation-risk rejection for shadow snapshot artifacts, read-only/release-gate metadata for monitor/preflight outputs, and regression coverage proving no active CPB/trade/paper-live/timer mutation. Verification: focused M82 pytest `45 passed`; full `PYTHONPATH=src:. pytest -q` (`430 passed, 3 skipped, 10 subtests passed`); `git diff --check`. |
| M83 | Shadow observation scorecard service and API | Done, Deployed | release `pgc-v0.1.0-20260513-m83-m86-r2` | Added read-only `shadow_observation_scorecard_v1` service/API/CLI over shadow snapshot, monitor artifacts, market bars, and hypotheses with explicit missing/insufficient-sample blockers plus portable artifact paths. Verification: focused M83-M86 pytest `103 passed, 1 skipped, 1 subtests passed`; full `PYTHONPATH=src:. pytest -q` (`439 passed, 3 skipped, 10 subtests passed`); `git diff --check`. |
| M84 | Dashboard observation queue and attribution view | Done, Deployed | release `pgc-v0.1.0-20260513-m83-m86-r2` | Extended Shadow Lab with read-only observation queue, outcome attribution drawer, score/coverage/blocker display, and explicit no promote/trade/plan/timer controls. Verification: `node --check web/dashboard/app.js`, Dashboard static tests, and full suite passed. |
| M85 | Daily report, CLI, and pipeline observation artifacts | Done, Deployed | release `pgc-v0.1.0-20260513-m83-m86-r2` | Added `shadow_observation` daily report JSON/Markdown alongside the legacy `shadow_strategy` block, compact observation status/top-candidate/blocker CLI lines for `ops shadow-snapshot` and `ops daily-pipeline`, and date-scoped `shadow_observation_scorecard_YYYYMMDD` artifacts from the monitor script without active pick/trade/timer mutation. Regenerated 20260512/20260513 artifacts. |
| M86 | Promotion dossier, guardrails, and release gate | Done, Deployed | release `pgc-v0.1.0-20260513-m83-m86-r2` | Added review-only `shadow_promotion_dossier_YYYYMMDD` artifacts with threshold metadata, blocked/readiness states, strategy-evolution artifact review, runbook release gate wording, portable source paths, and regression coverage proving no active CPB/trade/paper-live/timer mutation. |
| M87 | Shadow observation history index and API | Done, Deployed | release `pgc-v0.1.0-20260513-m87-m90-r1` | Added read-only `shadow_observation_history_v1` over scorecard/dossier artifacts with `/api/shadow-observation-history`, `ops shadow-observation-history`, candidate trend/rank/coverage/blocker/review history, explicit missing-artifact blockers, and no strategy/trade/paper-live/timer mutation. Verification: focused M87-M90 pytest `173 passed, 3 skipped, 1 subtests passed`; full `PYTHONPATH=src:. pytest -q` (`453 passed, 3 skipped, 10 subtests passed`); `git diff --check`. |
| M88 | Dashboard observation timeline and comparison UX | Done, Deployed | release `pgc-v0.1.0-20260513-m87-m90-r1` | Added Shadow Lab observation history date/window selector, history timeline strip, candidate trend cards, and comparison drawer over `shadow_observation_history_v1`; no promote/trade/plan/timer controls. Verification: `node --check web/dashboard/app.js`, Dashboard static tests, and full suite passed. |
| M89 | Promotion review request package | Done, Deployed | release `pgc-v0.1.0-20260513-m87-m90-r1` | Added `shadow_promotion_review_request_v1` JSON/Markdown artifacts from promotion dossiers, CLI generation/validation, blocked no-review-ready handling, required human decisions/replay evidence/rollback notes, and regression coverage proving no strategy-version or trading-state writes. Generated `reports/shadow_promotion_review_request_20260513.{json,md}` with `no_review_ready_candidates`. |
| M90 | Replay/backtest evidence bridge for shadow candidates | Done, Deployed | release `pgc-v0.1.0-20260513-m87-m90-r1` | Added `shadow_replay_backtest_evidence_v1` provider-file validation for candidate key/date range/sample/source-hash/no-future/metric completeness, surfaced accepted/rejected/missing evidence in scorecards, promotion dossiers, monitor artifacts, strategy-evolution reviews, and daily reports, and kept accepted evidence advisory-only with manual promotion blockers intact. |
| M91 | Shadow replay/backtest evidence producer | Done, Deployed | release `pgc-v0.1.0-20260513-m91-m94-r2` | Added read-only M90-compatible replay/backtest evidence generation via service/script/CLI, generated 20260513 artifacts for all five candidates, and validated 3 accepted shadow-bucket artifacts plus 2 explicit rejected blockers (`preconfirm_watchlist` stale source; `pullback_dip_buy` stale source + missing T1 metrics). Direct script smoke now works without manual `PYTHONPATH`. No strategy/trade/paper-live/timer mutation. |
| M92 | Dashboard promotion review workbench | Done, Deployed | release `pgc-v0.1.0-20260513-m91-m94-r2` | Added read-only Dashboard promotion review workbench over `shadow_promotion_review_request_v1` with candidate readiness, replay evidence accepted/rejected/missing counts, required human decisions, rollback notes, release blockers, and candidate detail drawer; API/workbench hydrates current replay evidence at read time so stale review-request artifacts cannot mask accepted/rejected evidence. No approve/promote/trade/plan/timer controls. |
| M93 | Daily pipeline shadow evidence closure | Done, Deployed | release `pgc-v0.1.0-20260513-m91-m94-r2` | Added daily report/pipeline shadow evidence closure checks for scorecard, dossier, review request, replay evidence, Dashboard history parity, and compact CLI blockers; monitor script now refreshes review request artifacts. |
| M94 | Shadow threshold calibration sandbox | Done, Deployed | release `pgc-v0.1.0-20260513-m91-m94-r2`; `reports/shadow_threshold_calibration_20260513.json` | Added artifact-only `shadow_threshold_calibration_v1` sandbox comparing current, quality-tightened, and exploratory shadow thresholds across family metrics, frozen-CPB deltas, replay evidence coverage, recommended next experiments, and rejected variants without editing active CPB params or publishing strategy versions. Verification: focused M91-M94 pytest `168 passed, 1 skipped, 1 subtests passed`; post-fix focused pytest `107 passed, 1 skipped, 1 subtests passed`; full `PYTHONPATH=src:. pytest -q` `463 passed, 3 skipped, 10 subtests passed`; `node --check web/dashboard/app.js`; Python compile; `git diff --check`; direct script dry-runs; secret/path scans. |
| M95 | Rejected evidence source closure | Done, Local | `reports/shadow_replay_backtest_evidence_20260513_preconfirm_watchlist.json`; `reports/shadow_replay_backtest_evidence_20260513_pullback_dip_buy.json` | Refreshed preconfirm and pullback dip-buy source evidence through 20260513 using local SQLite market bars overlay, added dip-buy T1 metrics, regenerated 20260513 replay/backtest evidence, and closed stale/metric-gap blockers without loosening validation. Verification: evidence preview `accepted=5 rejected=0`; focused pytest `16 passed`; `git diff --check`; safety scan confirmed artifact-only/no promote/trade/paper-live/timer mutation. |
| M96 | Shadow walk-forward outcome accumulator | Done, Local | `reports/shadow_walk_forward_outcomes_20260513.json` | Added date-scoped `shadow_walk_forward_outcomes_v1` artifact accumulation from shadow monitor signals and `market_bars`, including T+1/T+5 availability, partial-horizon/missing-bar/no-future diagnostics, monitor output links, daily pipeline summary fields, and daily report JSON/Markdown sections without strategy/trade/position/paper-live/timer writes. Verification: monitor generation command, focused M96 pytest `33 passed`, Python compile. |
| M97 | Shadow experiment registry | Done, Local | `reports/shadow_strategy_experiment_registry_20260513.json` | Added artifact-only `shadow_strategy_experiment_registry_v1` JSON/Markdown registry from M94 calibration recommendations, with required evidence, stop rules, frozen-CPB comparison, rollback rules, manual approval boundaries, and reviewer/script coverage. Verification: script generation, focused M97 pytest `45 passed`, Python compile, `git diff --check`, safety field check, and scoped path/secret scans. |
| M98 | Chinese shadow decision memo workbench | Done, Local | `/api/shadow-decision-memo`; Shadow Lab 中文决策备忘录; daily report `shadow_decision_memo` | Added read-only `shadow_decision_memo_v1` API/Dashboard/report view linking review request, replay evidence, walk-forward outcomes, calibration, and experiment registry with Chinese sections for 候选概览、证据状态、阻断原因、下一步实验、人工决策、风险/回滚边界. No approve/promote/trade/plan/timer controls. Verification: focused M98 pytest `67 passed, 1 skipped`; full pytest `471 passed, 3 skipped, 10 subtests passed`; `node --check`; Python compile; `git diff --check`; service smoke. |
| M99 | Dashboard Chinese-first UX pass | Done, Local | `web/dashboard/index.html`; `web/dashboard/app.js`; `tests/test_dashboard_static.py` | Localized user-visible Dashboard copy across execution, review/history, paper acceptance, market diagnostics, strategy hypothesis, Shadow Lab, detail drawers, and TradingAgents surfaces. Replaced visible `paper/live`, `advisory`, `open-execution`, `ranked signals`, `source_refs`, `external_data_coverage`, `Rank/Score/Coverage/Blockers`, and raw shadow candidate keys with Chinese-first labels while keeping API paths and internal contract keys intact. Verification: `node --check web/dashboard/app.js`; focused M95-M99 pytest `103 passed, 1 skipped`; full `PYTHONPATH=src:. pytest -q` `472 passed, 3 skipped, 10 subtests passed`; `git diff --check`. |
| OPS-20260511 | Daily review and new stock pool intake | Done, Applied | `reports/daily_review_20260511.md`; `data/daily_review_20260511_ops_summary.json` | Remote `paper-main` ops sync completed with `operator=azboo`: backed up remote DB to `/opt/pgc/backups/pgc_trading-20260511-170517-before-ops-20260511-sync.db` and `/opt/pgc/backups/pgc_trading_20260511_171526_905184_before_daily_pipeline_20260511.db`; ingested 6 screenshot-sourced 黑马集中营 events; refreshed remote `market_bars`/`daily_basic_snapshots` for 247 symbols on `20260511`; dry-run then remote apply pipeline passed; no new daily pick/trade plan because `no_strategy_signals`; server already had one manual executed buy for `301188.SZ` on `20260511`, now reflected in pulled local DB/report; evidence gaps remain explicit (`MARKET_EVIDENCE_MISSING`, `AGENT_EXTERNAL_EVIDENCE_MISSING`, `AGENT_REVIEW_NOT_RUN`, market-review shallow history warning). |

## Active Parallel Plan

| Lane | Task | Status | Depends On | Review Focus |
| --- | --- | --- | --- | --- |
| A | M95 Rejected evidence source closure | Done, Local | M91 evidence contract, source research artifacts | Closed stale/metric-gap evidence for preconfirm and dip-buy without loosening validation; all five 20260513 replay/backtest evidence artifacts now validate accepted and remain advisory-only. |
| B | M96 Shadow walk-forward outcome accumulator | Done, Local | M87 history, M91 evidence shape, market bars | Added post-close outcome accumulation plus no-future, missing-bar, and partial-horizon diagnostics; feeds monitor output, daily pipeline summaries, and daily report surfaces. |
| C | M97 Shadow experiment registry | Done, Local | M94 calibration artifact | Turned calibration recommendations into explicit artifact-only experiments and stop rules; registry remains advisory with `promotion_allowed=false` and no strategy/trade/timer writes. |
| D | M98 Chinese shadow decision memo workbench | Done, Local | M92 review workbench, M94 calibration | Chinese operator memo in API/Dashboard/report; no approve/promote/trade/plan/timer controls. |
| E | M99 Dashboard Chinese-first UX pass | Done, Local | User-reported English-heavy Dashboard issue after M95-M98 | Localized user-facing Dashboard labels, empty states, chips, drawer sections, market diagnostics, paper acceptance, TradingAgents copy, and shadow candidate names; static regression now asserts Chinese-first operator copy. |

## Review Rules For Future Sessions

- Do not mark a task Done only because code exists; require tests or an explicit review record.
- Any market-review output is advisory unless a later task explicitly changes that contract.
- Dashboard market-review pages remain read-only until a separate write task is approved.
- Missing sector/news/sentiment evidence must be visible as `missing`, `partial`, or `unknown`, never silently treated as safe.
- Strategy hypotheses must pass replay/backtest evidence before active strategy parameters or paper/live behavior change.
- Non-dry-run ledger writes require operator, idempotency/write-token rules, and account isolation.

## Update Protocol

When a task finishes:

1. Update the task row status and anchor commit.
2. Add the release tag when it is deployed.
3. Add the strongest verification result available.
4. Move newly unblocked tasks into the Active Parallel Plan.
5. Keep old plan docs as detailed history; do not duplicate their full specs here.

When planning new task IDs:

1. Create or update the detailed plan doc first.
2. Add every new task ID to the Milestone Ledger in the same turn.
3. Update Active Parallel Plan before telling the user to open child sessions.
4. Do not announce a new parallel task name unless it is discoverable from this ledger.
