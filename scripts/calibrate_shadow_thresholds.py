#!/usr/bin/env python3
"""Build artifact-only shadow threshold calibration reports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pgc_trading.config import Paths
from pgc_trading.services.common import RequestContext
from pgc_trading.services.strategy_evolution_service import (
    BuildShadowThresholdCalibrationRequest,
    StrategyEvolutionService,
    review_shadow_threshold_calibration_artifact,
)


DEFAULT_DB_PATH = Paths().db_path
DEFAULT_REPORTS_DIR = Paths().reports_dir


def main() -> int:
    args = parse_args()
    result = generate_shadow_threshold_calibration(
        db_path=args.db_path,
        reports_dir=args.reports_dir,
        as_of_date=args.date,
        output_path=args.output,
        dry_run=not args.apply,
        operator=args.operator,
    )
    print_shadow_threshold_calibration_result(result, compact=args.compact)
    return 0 if result["ok"] else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", "--as-of-date", dest="date", help="optional calibration date YYYYMMDD")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    parser.add_argument("--output", type=Path, help="optional JSON artifact output path")
    parser.add_argument("--operator", default="shadow-threshold-calibration")
    parser.add_argument("--compact", action="store_true", help="omit the full JSON artifact payload")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the calibration JSON/Markdown artifacts; default is an in-memory preview",
    )
    return parser.parse_args()


def generate_shadow_threshold_calibration(
    *,
    db_path: Path,
    reports_dir: Path,
    as_of_date: str | None = None,
    output_path: Path | None = None,
    dry_run: bool = True,
    operator: str | None = None,
) -> dict[str, Any]:
    service = StrategyEvolutionService(db_path=db_path, reports_dir=reports_dir)
    result = service.build_shadow_threshold_calibration(
        BuildShadowThresholdCalibrationRequest(
            as_of_date=as_of_date,
            output_path=str(output_path) if output_path is not None else None,
        ),
        RequestContext(
            request_id="script-shadow-threshold-calibration",
            dry_run=dry_run,
            operator=operator,
        ),
    )
    payload: dict[str, Any] = {
        "ok": result.ok,
        "status": result.status,
        "errors": [error.code for error in result.errors],
        "warnings": [warning.code for warning in result.warnings],
        "data": None,
    }
    if result.data is not None:
        review = None
        if result.data.artifact_path:
            review = review_shadow_threshold_calibration_artifact(result.data.artifact_path)
        payload["data"] = {
            "as_of_date": result.data.as_of_date,
            "would_write_artifact": result.data.would_write_artifact,
            "wrote_artifact": result.data.wrote_artifact,
            "artifact_path": result.data.artifact_path,
            "markdown_path": result.data.markdown_path,
            "summary": result.data.summary,
            "safety": {
                "active_params_mutated": result.data.active_params_mutated,
                "wrote_strategy_version": result.data.wrote_strategy_version,
                "wrote_strategy_versions": result.data.wrote_strategy_versions,
                "writes_trade_state": result.data.writes_trade_state,
                "writes_paper_live_behavior": result.data.writes_paper_live_behavior,
                "timer_mutated": result.data.timer_mutated,
            },
            "review_valid": review.valid if review is not None else None,
            "artifact": result.data.artifact,
        }
    return payload


def print_shadow_threshold_calibration_result(payload: dict[str, Any], *, compact: bool = False) -> None:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    safety = data.get("safety") if isinstance(data.get("safety"), dict) else {}
    print(f"shadow_threshold_calibration_status={payload.get('status')}")
    print("calibration_contract=shadow_threshold_calibration_v1")
    print(f"as_of_date={data.get('as_of_date') or 'unknown'}")
    print(f"wrote_artifact={_display_bool(data.get('wrote_artifact'))}")
    print(f"artifact_path={data.get('artifact_path') or 'dry-run'}")
    print(f"markdown_path={data.get('markdown_path') or 'dry-run'}")
    print(f"candidate_count={summary.get('candidate_count', 0)}")
    print(f"recommended_next_experiment_count={summary.get('recommended_next_experiment_count', 0)}")
    print(f"rejected_variant_count={summary.get('rejected_variant_count', 0)}")
    print("artifact_only=true")
    print("promotion_allowed=false")
    print(f"active_params_mutated={_display_bool(safety.get('active_params_mutated'))}")
    print(f"wrote_strategy_versions={_display_bool(safety.get('wrote_strategy_versions'))}")
    print(f"writes_trade_state={_display_bool(safety.get('writes_trade_state'))}")
    print(f"writes_paper_live_behavior={_display_bool(safety.get('writes_paper_live_behavior'))}")
    print(f"timer_mutated={_display_bool(safety.get('timer_mutated'))}")
    if data.get("review_valid") is not None:
        print(f"artifact_review_valid={_display_bool(data.get('review_valid'))}")
    if not compact and data.get("artifact"):
        print("shadow_threshold_calibration_json=" + json.dumps(data["artifact"], ensure_ascii=False, sort_keys=True))


def _display_bool(value: object) -> str:
    return "true" if bool(value) else "false"


if __name__ == "__main__":
    raise SystemExit(main())
