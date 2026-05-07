# M10 Paper Live Readiness Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Finish M10 by making the daily-close workflow operational for `paper-main`, proving paper ledger readiness, and preparing a guarded `live-main` dry-run path without automatic ordering.

**Architecture:** Keep the modular monolith boundary: CLI/API surfaces call application services, and only seed/migration utilities perform reference-data setup. Paper operations write through existing workflow, planning, execution, and position services; live preparation is dry-run only until a later explicit approval milestone. Account identity must be consistent across seed data, defaults, runbooks, tests, and Dashboard/API assumptions.

**Tech Stack:** Python 3, SQLite, argparse CLI, unittest/pytest, existing `pgc_trading.services.*` application services, existing migrations/seed utilities.

---

## Current Context

- Current branch: `main`, synced to `origin/main` after commit `9dcd1e5 Add daily close CLI workflow command`.
- Existing real CLI entrypoint: `pgc daily-close --date S --db-path DB --account paper-200k [--apply]`.
- M10 roadmap target names are `paper-main` and `live-main`.
- Current default account key is `paper-200k` in `src/pgc_trading/services/daily_close_workflow_service.py`.
- `src/pgc_trading/storage/database.py::seed_account()` is stale against migration `003_accounts.sql` because it inserts `portfolio_accounts` without `account_key`.
- `PortfolioPlanningService` currently rejects non-paper accounts, so `live-main` dry-run needs an explicit guarded path before any live readiness rehearsal can pass.
- Do not mutate `data/pgc_trading.db` unless the user explicitly asks for a real local paper run.
- Do not commit secrets, broker credentials, real tokens, or plaintext infrastructure passwords.

## Milestone Split

| Milestone | Purpose | Primary Output |
| --- | --- | --- |
| M10A Account Catalog | Align account names and seed behavior | `paper-main` and `live-main` seedable, `seed_account()` fixed |
| M10B Paper Daily-Close Smoke | Prove CLI can create a plan on a migrated seeded DB | temp-DB smoke/integration test for `pgc daily-close --apply` |
| M10C Paper Readiness Gate | Measure paper acceptance criteria | service + CLI summary for trades, exits, blockers, invariants |
| M10D Live Dry-Run Guard | Prepare live rehearsal safely | `live-main` dry-run works, non-dry live plan writes remain blocked |
| M10E Runbook & Final Gate | Make operation repeatable | updated runbook/contracts, full verification, commit/push |

## M10A: Account Catalog And Seed Alignment

**Priority:** P0

**Goal:** Make `paper-main` and `live-main` first-class reference accounts while preserving idempotent seed behavior.

**Files:**

- Modify: `src/pgc_trading/config.py`
- Modify: `src/pgc_trading/storage/seed.py`
- Modify: `src/pgc_trading/storage/database.py`
- Modify: `src/pgc_trading/services/daily_close_workflow_service.py`
- Modify: `src/pgc_trading/cli/main.py`
- Modify: `src/pgc_trading/api/routes.py`
- Modify: tests that still hard-code `paper-200k`
- Test: `tests/test_reference_seed.py`
- Test: `tests/test_cli_main.py`
- Test: `tests/test_api_read_routes.py`
- Test: `tests/test_api_write_routes.py`
- Test: existing portfolio/workflow/report tests with account constants

**Step 1: Write failing seed tests**

Add or update tests in `tests/test_reference_seed.py`:

```python
def test_reference_seed_writes_paper_main_and_live_main_accounts(self) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "pgc.db"
        run_migrations(db_path)

        result = seed_reference_data(db_path)

        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                """
                SELECT account_key, name, account_type, initial_cash, max_positions, position_sizing, status
                FROM portfolio_accounts
                ORDER BY account_key
                """
            ).fetchall()

        self.assertEqual(
            [(row[0], row[2], row[4], row[5], row[6]) for row in rows],
            [
                ("live-main", "live", 3, "equal_slots", "active"),
                ("paper-main", "paper", 3, "equal_slots", "active"),
            ],
        )
        self.assertIn("portfolio_account_paper_main", result.ids)
        self.assertIn("portfolio_account_live_main", result.ids)
```

Add a stale-schema regression test:

```python
def test_seed_account_writes_required_account_key(self) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "pgc.db"
        run_migrations(db_path)

        account_id = seed_account(AccountConfig(account_key="paper-main"), db_path)

        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT id, account_key, account_type FROM portfolio_accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
        self.assertEqual(row, (account_id, "paper-main", "paper"))
```

**Step 2: Run tests to verify failure**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_reference_seed
```

Expected: fails because `AccountConfig.account_key` does not exist, only one account is seeded, and/or `seed_account()` omits `account_key`.

**Step 3: Implement account config and seed helpers**

Implementation intent:

- Add `account_key: str | None = "paper-main"` and `account_type: str = "paper"` to `AccountConfig`.
- Add a helper in `src/pgc_trading/storage/seed.py` that upserts any account type accepted by `003_accounts.sql`.
- Seed default accounts:
  - `paper-main`: paper, initial cash 200000, max positions 3, equal slots, active.
  - `live-main`: live, initial cash 200000 for dry-run sizing only, max positions 3, equal slots, active.
- Keep `ReferenceSeedResult.ids["portfolio_account"]` pointing to `paper-main` for backward compatibility inside tests that only need a default paper account.
- Fix `seed_account()` in `src/pgc_trading/storage/database.py` to include `account_key` and `account_type`.

**Step 4: Canonicalize defaults**

Change `DEFAULT_ACCOUNT_KEY` from `paper-200k` to `paper-main` in `src/pgc_trading/services/daily_close_workflow_service.py`.

Update hard-coded test constants and docs/UI defaults that are part of executable behavior. At minimum update:

```bash
rg -n "paper-200k" src tests docs/ui reports/operational_runbook_design.md
```

Keep historical report artifacts unchanged unless a test imports them.

**Step 5: Run focused verification**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_reference_seed
PYTHONPATH=src python3 -m unittest tests.test_cli_main
PYTHONPATH=src python3 -m unittest tests.test_api_read_routes tests.test_api_write_routes
```

Expected: all focused tests pass.

**Step 6: Commit**

```bash
git add src/pgc_trading/config.py src/pgc_trading/storage/seed.py src/pgc_trading/storage/database.py src/pgc_trading/services/daily_close_workflow_service.py src/pgc_trading/cli/main.py src/pgc_trading/api/routes.py tests
git commit -m "Align operational account seed defaults"
```

## M10B: Paper Daily-Close CLI Smoke

**Priority:** P0

**Goal:** Prove `pgc daily-close --apply` creates one paper daily pick and one active buy plan through the real CLI on a temp migrated DB.

**Files:**

- Create: `tests/helpers/daily_workflow_fixture.py`
- Create: `tests/test_cli_daily_close_integration.py`
- Modify only if needed: `tests/test_daily_close_workflow_service.py` to reuse the helper

**Step 1: Extract fixture helpers**

Move the temp data setup currently duplicated in `tests/test_daily_close_workflow_service.py` into `tests/helpers/daily_workflow_fixture.py`:

```python
AS_OF_DATE = "20260504"
ENTRY_DATE = "20260427"
BUY_DATE = "20260505"

def migrated_seeded_daily_close_db(tmp: str | Path) -> Path:
    db_path = Path(tmp) / "pgc.db"
    run_migrations(db_path)
    seed_reference_data(db_path)
    return db_path

def insert_open_calendar(conn: sqlite3.Connection) -> None:
    ...

def insert_contracting_pullback_case(conn: sqlite3.Connection, ts_code: str, name: str, price_scale: float = 1.0) -> int:
    ...
```

Use the existing SQL from `tests/test_daily_close_workflow_service.py` without changing test semantics.

**Step 2: Write CLI integration test**

Create `tests/test_cli_daily_close_integration.py`:

```python
def test_daily_close_apply_creates_paper_plan_through_cli(self) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = migrated_seeded_daily_close_db(tmp)
        with sqlite3.connect(db_path) as conn:
            insert_open_calendar(conn)
            insert_contracting_pullback_case(conn, "000001.SZ", "CLI Paper Pick")

        stdout = io.StringIO()
        code = cli_main(
            [
                "daily-close",
                "--date",
                "2026-05-04",
                "--db-path",
                str(db_path),
                "--account",
                "paper-main",
                "--apply",
                "--operator",
                "tester",
            ],
            stdout=stdout,
        )

        self.assertEqual(code, 0)
        output = stdout.getvalue()
        self.assertIn("workflow_status=plan_ready", output)
        self.assertIn("buy_plan=id=", output)

        with sqlite3.connect(db_path) as conn:
            self.assertEqual(_count(conn, "daily_picks"), 1)
            self.assertEqual(_count(conn, "trade_plans"), 1)
            self.assertEqual(_count(conn, "trades"), 0)
            self.assertEqual(_count(conn, "positions"), 0)
```

Also add a default preview integration test proving no writes:

```python
def test_daily_close_preview_does_not_persist_pick_or_plan(self) -> None:
    ...
    code = cli_main([... no "--apply" ...], stdout=stdout)
    self.assertEqual(code, 0)
    self.assertEqual(_count(conn, "daily_picks"), 0)
    self.assertEqual(_count(conn, "trade_plans"), 0)
```

**Step 3: Run focused tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_cli_daily_close_integration tests.test_daily_close_workflow_service
```

Expected: new tests pass; workflow service tests still pass with shared fixture.

**Step 4: Commit**

```bash
git add tests/helpers/daily_workflow_fixture.py tests/test_cli_daily_close_integration.py tests/test_daily_close_workflow_service.py
git commit -m "Add paper daily close CLI smoke coverage"
```

## M10C: Paper Readiness Gate

**Priority:** P0

**Goal:** Provide a deterministic paper-readiness check that answers whether `paper-main` is ready to consider live preparation.

**Files:**

- Create: `src/pgc_trading/services/operational_readiness_service.py`
- Modify: `src/pgc_trading/cli/main.py`
- Create: `tests/test_operational_readiness_service.py`
- Modify: `tests/test_cli_main.py`

**Acceptance criteria checked by the service:**

- Minimum paper trades count defaults to 10.
- No duplicate open positions for the same account and symbol.
- No open data quality blockers.
- No positions with unhandled T+2/T+5 decisions as of the requested date.
- Invariant report from `check_database()` is clean.
- Cash/equity sanity can be reported as warning if the current schema cannot prove exact reconciliation yet.

**Step 1: Write service tests**

Create tests for:

- `blocked` when account has fewer than 10 trades.
- `blocked` when `check_database()` returns violations.
- `blocked` when an open data-quality blocker exists.
- `pass` when temp fixture has 10 completed paper trades, no open blockers, and no due exits.

Expected DTO shape:

```python
@dataclass(frozen=True)
class PaperReadinessResult:
    account_key: str
    as_of_date: str
    readiness: str
    trades_count: int
    open_positions_count: int
    due_exit_positions_count: int
    open_blockers_count: int
    invariant_ok: bool
```

**Step 2: Implement minimal service**

Use structured SQL queries and existing `check_database(self.db_path)`.

Return:

- `ServiceResult(status="success", data=..., warnings=[...])` when readiness is `pass` or `warning`.
- `ServiceResult(status="blocked", data=..., errors=[...])` when any P0 blocker exists.

**Step 3: Add CLI command**

Add `paper-readiness` to `src/pgc_trading/cli/main.py`:

```bash
pgc paper-readiness --date 2026-05-07 --db-path data/pgc_trading.db --account paper-main --min-trades 10
```

Output must include:

```text
readiness=pass|warning|blocked
trades_count=N
open_positions_count=N
due_exit_positions_count=N
open_blockers_count=N
invariant_ok=true|false
```

**Step 4: Run focused tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_operational_readiness_service tests.test_cli_main
```

Expected: all focused tests pass.

**Step 5: Commit**

```bash
git add src/pgc_trading/services/operational_readiness_service.py src/pgc_trading/cli/main.py tests/test_operational_readiness_service.py tests/test_cli_main.py
git commit -m "Add paper operational readiness gate"
```

## M10D: Live Dry-Run Guard

**Priority:** P0

**Goal:** Allow `live-main` readiness rehearsal in dry-run mode while continuing to block non-dry live plan writes.

**Files:**

- Modify: `src/pgc_trading/services/portfolio_planning_service.py`
- Modify: `src/pgc_trading/services/daily_close_workflow_service.py` only if workflow-level error mapping is needed
- Modify: `src/pgc_trading/api/routes.py` only if API needs a clearer live dry-run validation response
- Test: `tests/test_daily_close_workflow_service.py`
- Test: `tests/test_api_write_routes.py`

**Step 1: Write failing workflow tests**

Add tests:

```python
def test_live_main_dry_run_builds_non_persisted_plan_preview(self) -> None:
    ...
    result = DailyCloseWorkflowService(db_path).run_daily_close(
        RunDailyCloseWorkflowRequest(as_of_date=AS_OF_DATE, account_key="live-main", run_type="live"),
        RequestContext(request_id="req-live-dry", dry_run=True, operator="tester"),
    )
    self.assertEqual(result.status, "success")
    self.assertEqual(result.data.workflow_status, "plan_ready")
    self.assertIsNone(result.data.buy_plan.trade_plan_id)
    self.assertEqual(_count(conn, "trade_plans"), 0)

def test_live_main_apply_is_blocked_until_explicit_live_enablement(self) -> None:
    ...
    result = DailyCloseWorkflowService(db_path).run_daily_close(
        RunDailyCloseWorkflowRequest(as_of_date=AS_OF_DATE, account_key="live-main", run_type="live"),
        RequestContext(request_id="req-live-apply", dry_run=False, operator="tester"),
    )
    self.assertIn(result.status, {"blocked", "validation_failed"})
    self.assertEqual(_count(conn, "trade_plans"), 0)
```

**Step 2: Implement account-type guard in planning service**

Change `_resolve_account()` to accept an explicit live dry-run flag, for example:

```python
def _resolve_account(..., allow_live_dry_run: bool = False) -> _Account | ServiceError:
    ...
    if row["account_type"] == "live" and allow_live_dry_run:
        return _Account(...)
    if row["account_type"] != "paper":
        return ServiceError(
            code="LIVE_PLAN_APPLY_DISABLED" if row["account_type"] == "live" else "UNSUPPORTED_ACCOUNT_TYPE",
            message="Live account planning is dry-run only until live enablement is approved.",
            entity_type="portfolio_account",
            entity_id=int(row["id"]),
            severity="blocker",
        )
```

Pass `allow_live_dry_run=ctx.dry_run` from buy-plan generation. Do not allow publish, cancel, execution recording, or sell-plan generation for live accounts in this milestone unless a test explicitly proves dry-run-only behavior.

**Step 3: Run focused tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_daily_close_workflow_service tests.test_api_write_routes
```

Expected: live dry-run passes with no writes; live apply is blocked.

**Step 4: Commit**

```bash
git add src/pgc_trading/services/portfolio_planning_service.py src/pgc_trading/services/daily_close_workflow_service.py src/pgc_trading/api/routes.py tests/test_daily_close_workflow_service.py tests/test_api_write_routes.py
git commit -m "Guard live daily close dry runs"
```

## M10E: Runbook, Contracts, And Final Gate

**Priority:** P0

**Goal:** Make the operational path clear enough that the next session can run paper trades and review readiness without guessing.

**Files:**

- Modify: `reports/operational_runbook_design.md`
- Modify: `reports/api_cli_contract_design.md`
- Modify: `docs/ui/open-design-pgc-dashboard-brief.md` if account defaults changed
- Modify: `docs/plans/2026-05-06-pgc-development-supervision-plan.md`

**Step 1: Update account names and commands**

Replace operational examples that still use `paper-200k` or stale `pgc review run` syntax with:

```bash
pgc daily-close --date S --db-path data/pgc_trading.db --account paper-main
pgc daily-close --date S --db-path data/pgc_trading.db --account paper-main --apply --operator azboo
pgc paper-readiness --date S --db-path data/pgc_trading.db --account paper-main --min-trades 10
pgc daily-close --date S --db-path data/pgc_trading.db --account live-main --run-type live
```

Keep live examples dry-run only. Do not document live `--apply` as approved.

**Step 2: Update supervision board**

Append M10 work packages to `docs/plans/2026-05-06-pgc-development-supervision-plan.md`:

```markdown
| DEV11 M10 Account Catalog | planned | DEV10 | seed/config/tests | paper-main/live-main account readiness |
| DEV12 M10 Paper Smoke | planned | DEV11 | CLI/workflow/tests | daily-close apply smoke |
| DEV13 M10 Paper Readiness | planned | DEV12 | readiness service/CLI/tests | paper acceptance gate |
| DEV14 M10 Live Dry Run | planned | DEV13 | planning/workflow/tests | live-main dry-run only |
```

**Step 3: Run final verification**

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m pytest -q
python3 -m compileall -q src scripts tests
git diff --check
rg -n "(sk-[A-Za-z0-9]|TUSHARE_TOKEN|password|secret|api[_-]?key)" src tests docs reports scripts
```

Expected:

- unittest passes.
- pytest passes.
- compileall has no output.
- `git diff --check` has no output.
- secret scan has no real secret matches. If it matches placeholder docs, inspect and either rewrite placeholders or record why they are safe.

**Step 4: Commit and push**

```bash
git add reports/operational_runbook_design.md reports/api_cli_contract_design.md docs/ui/open-design-pgc-dashboard-brief.md docs/plans/2026-05-06-pgc-development-supervision-plan.md
git commit -m "Document M10 paper and live readiness operations"
git push origin main
```

## Execution Order Recommendation

1. Execute M10A alone and stop for review, because account default changes touch many tests.
2. Execute M10B next; it proves the daily-close CLI is not just unit-tested.
3. Execute M10C; this creates the objective "paper complete" gate.
4. Execute M10D only after M10C passes, because live dry-run should not distract from paper readiness.
5. Execute M10E as the final docs and verification pass.

## Do Not Do In M10

- Do not place real broker credentials in code, docs, tests, or fixtures.
- Do not implement automatic live ordering.
- Do not let Agent output automatically block or size trades.
- Do not mutate `data/pgc_trading.db` during tests.
- Do not mix `paper-main` trades into `live-main`.
- Do not change strategy parameters as part of operational readiness.

## Suggested Checkpoint Protocol

After each milestone:

1. Run the milestone's focused tests.
2. Run `git diff --check`.
3. Run a scoped secret scan over changed files.
4. Commit with the milestone message.
5. Report status and wait for user review before moving to the next milestone.

