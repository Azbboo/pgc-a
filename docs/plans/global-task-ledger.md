# Global Task Ledger

Last updated: 2026-05-09

This ledger is the single index for historical and active project work. Detailed specs remain in the linked plan and design documents; this file tracks the global status, release anchors, and next dependencies.

## Current Release State

| Field | Value |
| --- | --- |
| Branch | `codex/m14b-yfinance` |
| Latest deployed commit | See release tag `pgc-v0.1.0-20260509-m41b-m46` |
| Latest release tag | `pgc-v0.1.0-20260509-m41b-m46` |
| Remote API | `http://150.158.121.150:8020` |
| Remote migration state | `012_market_review`, `pending_migrations=none` |
| Latest release health | `api_health_ok=true`, HTTP `200` |
| Latest full verification | `334 passed, 3 skipped, 10 subtests passed` locally on 2026-05-09; deploy script ran `330 tests`, `OK (skipped=3)` |

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
| M47 | Data evidence closed loop | Done / Local verification | Local verification 2026-05-09 | Provider-tagged market/sector/stock news, sentiment, policy, and research evidence with freshness/coverage states; no live web fetch in trading path. |
| M48 | Full-market Dashboard interaction upgrade | Done / Local verification | Local verification 2026-05-09 | Cross-day selector, history strip, sector/evidence drawers, source metadata, and plan relationship view added; verified with Dashboard/API static tests and full suite. |
| M49 | TradingAgents Chinese structured report | Done / Local verification | Local verification 2026-05-09 | Chinese source-labeled TradingAgents sections for fundamentals, news, sentiment, technicals, sector context, risks, conclusion, raw artifacts, and unavailable fallback. |
| M50 | Strategy evolution validation loop | Done / Local verification | Local verification 2026-05-09 | Hypothesis evidence/backtest gates before acceptance; accepted hypotheses create future strategy-version tasks only. |
| M51 | Review timeline and cross-day comparison | Next | `docs/plans/2026-05-09-m51-m54-release-timeline-ops-plan.md` | Compare daily review, full-market review, plan context, and open-execution state across dates without changing execution context accidentally. |
| M52 | Scheduled pipeline activation and ops monitor | Next | `docs/plans/2026-05-09-m51-m54-release-timeline-ops-plan.md` | Formal timer activation checklist, health/journal/rollback commands, and duplicate-write guardrails; timer still requires explicit operator enablement. |
| M53 | Release M47-M50 checkpoint | Next | `docs/plans/2026-05-09-m51-m54-release-timeline-ops-plan.md` | Deploy pushed M47-M50 commit, run remote health, update ledger from local verification to deployed, and keep timer disabled unless explicitly enabled. |
| M54 | Production evidence import operations | Next | `docs/plans/2026-05-09-m51-m54-release-timeline-ops-plan.md` | Repeatable provider-file evidence imports with dry-run coverage, stale/duplicate/missing summaries, and source-hash idempotency. |

## Active Parallel Plan

| Lane | Task | Status | Depends On | Review Focus |
| --- | --- | --- | --- | --- |
| A | M53 Release M47-M50 checkpoint | Next | M47-M50 pushed commit `159382f` | Deploy, remote health, ledger deployed status; timer remains disabled unless explicitly enabled. |
| B | M51 Review timeline and cross-day comparison | Next | M47/M48 data shape stable | Cross-day navigation must not override execution-date context. |
| C | M52 Scheduled pipeline activation and ops monitor | Next | M46 timer installer, M47/M49 evidence gates stable | Dry-run first, explicit operator enablement, journal/status/rollback documented. |
| D | M54 Production evidence import operations | Next | M47 evidence contract, M49 Agent evidence cache | Provider-file contract, dry-run coverage, source-hash idempotency, no live fetch in trading path. |

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
