# Dashboard Operator Flow QA 2026-05-14

Scope: M109 Dashboard operator flow polish after production QA.

Changed surfaces:
- 每日复盘、全市场复盘、证据/运维、影子策略新增统一操作快览，固定呈现“今天该看什么 / 为什么不能做 / 下一步点哪里”。
- 证据/运维卡片新增统一详情抽屉入口，详情按“结论 / 证据 / 来源 / 阻断原因 / 下一步 / 详情分组”展示。
- 统一详情抽屉增加分组左侧色条，强化证据、阻断、下一步等中文分组。

Verification:
- `node --check web/dashboard/app.js` passed.
- `PYTHONPATH=src:. pytest -q tests/test_dashboard_static.py` passed: `34 passed, 1 skipped`.
- `git diff --check` passed.
- Local read-only API health passed: `status=ok`, `writes_enabled=false`, `database_configured=true`.
- Dashboard HTML and versioned `app.js` / `styles.css` assets served from `http://127.0.0.1:8000/dashboard/`.

Visual smoke note:
- Attempted Playwright desktop/mobile smoke for 每日复盘、全市场复盘、证据/运维、影子策略 and ops drawer grouping.
- The bundled Playwright package was present, but the Chromium browser binary was missing locally.
- A browser download was approved and started, but remained too slow to complete in-session; the download process was stopped to avoid leaving a long-running network task.
- No screenshot artifact was captured in this run; static layout guards and HTTP asset checks remain the available QA evidence.

Safety:
- No new approve, promote, trade, plan-create, broker, paper-live, or timer controls were added.
- New operator-flow actions only navigate existing pages, refresh read views, or open existing detail drawers; plan publishing remains behind the existing transaction-plan/detail workflow.
