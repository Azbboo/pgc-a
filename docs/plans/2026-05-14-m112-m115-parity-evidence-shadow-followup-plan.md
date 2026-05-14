# M112-M115 Parity, Evidence, Dashboard, And Shadow Follow-Up Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close the operational gaps found during M108-M111 review: remote/local parity is still blocked by evidence and paper-ledger divergence, provider-pack evidence must be reproducible outside ignored run folders, Dashboard operator-flow work needs real browser screenshots, and the new shadow v2 weight research artifact needs formal governance before it can influence any future paper decision.

**Architecture:** Keep all lanes operator-led. Evidence imports may write only through existing reviewed-file ops commands with backup/operator/idempotency evidence. Shadow v2 remains research-only and must not mutate active CPB params, strategy versions, trade plans, trades, positions, broker state, paper/live behavior, or timers.

---

## Parallel Map

| Lane | Task | Can Run In Parallel | Primary Write Scope | Review Focus |
| --- | --- | --- | --- | --- |
| A | M112 Remote parity blocker closure | Mostly | remote ops evidence, parity reports, ledger updates | Import reviewed evidence remotely or pull/sync paper ledger until M108 parity blockers are understood and closed |
| B | M113 Provider-pack archival and reproducibility | Yes | durable provider-pack artifacts, reports, evidence ledger tests | No `.pgc-runs`-only source of truth; paths portable; hashes reproducible |
| C | M114 Dashboard real-browser visual and interaction QA | Yes | Dashboard CSS/JS, visual QA screenshots/report, static tests | Verify operator-flow strips/drawers on desktop/mobile with real browser pixels |
| D | M115 Shadow v2 research governance | Yes | `scripts/backtest_shadow_v2_weights.py`, reports, tests, runbook/ledger | Formalize research-only weight optimization; Chinese artifacts; no promotion/trading writes |

## M112: Remote Parity Blocker Closure

**Goal:** Convert the M108 parity blockers into either `pass` or explicit accepted operational blockers with fresh evidence.

**Steps:**
1. Backup remote DB before any non-dry-run evidence import or ledger sync.
2. Re-run `ops remote-local-parity` using fresh remote DB/report snapshots.
3. Close `evidence_imports` by importing reviewed 20260514 provider files on remote, or document why remote must remain stale.
4. Close `paper_ledger` by pulling production DB locally or reconciling local stale ledger state against remote as source of truth.
5. Re-render `reports/remote_local_parity_20260514.{json,md}` and update the ledger.

**Verification:** remote health with `--require-current-migrations`, parity command, focused parity tests, and `git diff --check`.

## M113: Provider-Pack Archival And Reproducibility

**Goal:** Make M110 evidence packs auditable after deployment instead of depending on ignored `.pgc-runs` paths.

**Steps:**
1. Choose a durable tracked or remote-backed evidence archive path for provider-pack manifests and reviewed files.
2. Ensure daily reports and evidence coverage ledger use portable paths, not machine-local absolute paths.
3. Add tests for portable provider-pack manifest/source-file paths in report JSON.
4. Document replay/import commands for child sessions and remote ops.

**Verification:** evidence-pack focused tests, report tests, path scan, and source-hash QA.

## M114: Dashboard Real-Browser Visual And Interaction QA

**Goal:** Finish the M109 QA gap by using a real browser to verify the new operator-flow strips and grouped drawers.

**Steps:**
1. Start local read-only API/Dashboard.
2. Capture desktop and mobile screenshots for 每日复盘、全市场复盘、证据/运维、影子策略, including 运维详情 drawer.
3. Check no horizontal overflow, clipped text, raw internal English labels, or broken drawer grouping.
4. Fix Dashboard CSS/JS if screenshots reveal layout issues.

**Verification:** visual QA report/screenshots, `node --check web/dashboard/app.js`, Dashboard static tests, and local HTTP smoke.

## M115: Shadow v2 Research Governance

**Goal:** Turn the research-only `shadow_weight_optimization_v1` seed into a governed observation workflow without giving it execution authority.

**Steps:**
1. Review `scripts/backtest_shadow_v2_weights.py`, `reports/shadow_weight_optimization_20260514.*`, and `reports/shadow_tomorrow_plan_20260515.md` for scope, Chinese readability, and no-future safety.
2. Add or tighten tests proving no active CPB params, strategy versions, trade plans, trades, positions, paper/live behavior, broker, or timer mutation.
3. Add Chinese operator output and runbook notes for how to use shadow v2 as observation evidence only.
4. Decide whether Dashboard should display this as a read-only research card in a later task; do not add controls yet.

**Verification:** script tests, Python compile, path/secret scan, and full suite if shared shadow utilities change.

## Integration Gate

After M112-M115 complete:

1. Run focused checks for changed services/scripts/Dashboard/report paths.
2. Run full suite: `PYTHONPATH=src:. pytest -q`.
3. Update `docs/plans/global-task-ledger.md` with task status and release anchors.
4. Commit, push, deploy with `bash scripts/deploy_remote.sh --release-tag pgc-v0.1.0-20260514-m112-m115-parity-evidence-shadow-r1`.
5. Run remote `ops health --require-current-migrations`.

