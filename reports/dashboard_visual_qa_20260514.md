# Dashboard Visual QA 2026-05-14

Scope: M104 production visual QA for the read-only Chinese Dashboard.

Local target:
- `http://127.0.0.1:8000/dashboard/`
- API health: `status=ok`, `writes_enabled=false`, `database_configured=true`

Viewports:
- Desktop: `1440x1100`
- Mobile: `390x1100`, device scale factor `2`

Pages captured:

| Page | Desktop | Mobile | Result |
| --- | --- | --- | --- |
| 开盘执行 | `reports/m104_visual_qa_20260514/execution_desktop.png` | `reports/m104_visual_qa_20260514/execution_mobile.png` | Pass |
| 每日复盘 | `reports/m104_visual_qa_20260514/review_desktop.png` | `reports/m104_visual_qa_20260514/review_mobile.png` | Pass |
| 全市场复盘 | `reports/m104_visual_qa_20260514/market_desktop.png` | `reports/m104_visual_qa_20260514/market_mobile.png` | Pass |
| 证据/运维 | `reports/m104_visual_qa_20260514/ops_desktop.png` | `reports/m104_visual_qa_20260514/ops_mobile.png` | Pass |
| 影子策略 | `reports/m104_visual_qa_20260514/shadow_desktop.png` | `reports/m104_visual_qa_20260514/shadow_mobile.png` | Pass |

Findings fixed:
- Removed the external Google Fonts import so production Dashboard rendering no longer depends on a remote font fetch.
- Renamed the production acceptance lanes in navigation and headings: `全市场复盘`, `证据/运维`, `影子策略实验室`.
- Added wrapping and min-width protections for navigation labels, page headings, toolbars, panel headings, chips, empty states, shadow review notes, and mobile market history pills.
- Localized visible shadow-review dynamic values such as `review_ready`, `manual_promotion_approval_required`, `no_review_ready_candidates`, `experiment registry`, and `blocker`.

Diagnostics:
- Desktop pages: document `scrollWidth == clientWidth`, no detected visible overflow.
- Mobile pages: document `scrollWidth == clientWidth`; the full-market sector table remains inside its scoped `.table-wrap` horizontal data-table container.
- Targeted dynamic English flags were absent after the final capture. Full diagnostics are in `reports/m104_visual_qa_20260514/diagnostics.json`.
