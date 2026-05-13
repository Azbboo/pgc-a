#!/usr/bin/env python3
"""Generate M90-compatible shadow replay/backtest evidence artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pgc_trading.config import Paths
from pgc_trading.services.common import RequestContext
from pgc_trading.services.shadow_observation_service import (
    BuildShadowReplayBacktestEvidenceRequest,
    ShadowObservationService,
)


def main() -> int:
    args = parse_args()
    payload = generate_shadow_replay_backtest_evidence(
        db_path=args.db_path,
        reports_dir=args.reports_dir,
        as_of_date=args.date,
        output_dir=args.output_dir,
        candidate_keys=tuple(args.candidate_key or ()),
        required_sample_size=args.required_sample_size,
        apply=bool(args.apply),
        operator=args.operator,
    )
    if args.compact:
        summary = payload.get("summary", {})
        print(
            "shadow_replay_backtest_evidence="
            f"status={payload.get('status')} "
            f"candidates={summary.get('candidate_count', 0)} "
            f"accepted={summary.get('accepted_count', 0)} "
            f"rejected={summary.get('rejected_count', 0)} "
            f"missing={summary.get('missing_count', 0)} "
            f"wrote_artifacts={str(bool(summary.get('wrote_artifacts'))).lower()}"
        )
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload.get("ok") else 1


def parse_args() -> argparse.Namespace:
    paths = Paths()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", "--as-of-date", dest="date", help="shadow monitor date YYYYMMDD or YYYY-MM-DD")
    parser.add_argument("--db-path", type=Path, default=paths.db_path)
    parser.add_argument("--reports-dir", type=Path, default=paths.reports_dir)
    parser.add_argument("--output-dir", type=Path, help="directory for generated evidence JSON files")
    parser.add_argument(
        "--candidate-key",
        action="append",
        default=[],
        help="candidate key to generate; repeat to limit generation",
    )
    parser.add_argument("--required-sample-size", type=int, default=20)
    parser.add_argument("--operator", default="cli")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write evidence artifacts; default previews and validates in memory",
    )
    parser.add_argument("--compact", action="store_true", help="print one compact status line")
    return parser.parse_args()


def generate_shadow_replay_backtest_evidence(
    *,
    db_path: Path,
    reports_dir: Path,
    as_of_date: str | None,
    output_dir: Path | None = None,
    candidate_keys: tuple[str, ...] = (),
    required_sample_size: int = 20,
    apply: bool = False,
    operator: str | None = None,
) -> dict[str, Any]:
    service = ShadowObservationService(db_path, reports_dir=reports_dir)
    result = service.build_replay_backtest_evidence(
        BuildShadowReplayBacktestEvidenceRequest(
            as_of_date=as_of_date,
            output_dir=str(output_dir) if output_dir is not None else None,
            candidate_keys=candidate_keys,
            required_sample_size=required_sample_size,
        ),
        RequestContext(
            request_id="script-shadow-replay-backtest-evidence",
            dry_run=not apply,
            operator=operator,
            source="script",
        ),
    )
    data = asdict(result.data) if result.data is not None else {}
    return {
        "ok": result.ok,
        "status": result.status,
        "errors": [asdict(error) for error in result.errors],
        "warnings": [asdict(warning) for warning in result.warnings],
        **data,
    }


if __name__ == "__main__":
    raise SystemExit(main())
