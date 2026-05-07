from __future__ import annotations

import copy
import json
import sqlite3
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pgc_trading.services.common import RequestContext
from pgc_trading.services.daily_review_service import (
    DailyReviewService,
    RunDailyReviewRequest,
)
from pgc_trading.storage.migrate import run_migrations
from pgc_trading.storage.seed import seed_reference_data


FIXTURE = Path(__file__).parent / "fixtures" / "replay" / "daily_workflow_golden_replay.json"
FORBIDDEN_OUTPUT_TOKENS = ("future", "label", "mfe", "mae", "return_20d", "winner_ret")


@dataclass(frozen=True)
class _ReplayRun:
    result: Any
    feature_run: dict[str, Any]
    snapshots: dict[str, dict[str, Any]]
    signals: list[dict[str, Any]]


class DailyWorkflowReplayTest(unittest.TestCase):
    def test_daily_workflow_matches_golden_and_proves_no_future_inputs(self) -> None:
        fixture = _load_fixture()

        replay = _run_fixture_replay(fixture)

        self.assertEqual(_actual_golden(replay), fixture["expected"])
        self.assertEqual(replay.result.errors, [])
        for snapshot in replay.snapshots.values():
            self._assert_no_future_labels(snapshot["features"])
            self.assertLessEqual(snapshot["features"]["latest_bar_date"], fixture["review_date"])
            self.assertLessEqual(
                snapshot["features"]["cpb_v2_context_source_review_date"],
                fixture["review_date"],
            )

    def test_visible_strategy_input_change_changes_hash_and_breaks_golden(self) -> None:
        fixture = _load_fixture()
        expected = fixture["expected"]
        mutated = copy.deepcopy(fixture)
        for snapshot in mutated["context_snapshots"]:
            if snapshot["raw_event_id"] == 2 and snapshot["review_date"] == fixture["review_date"]:
                snapshot["features"]["gap_from_trigger_close"] = 0.021

        replay = _run_fixture_replay(mutated)
        mutated_snapshot = replay.snapshots["000003.SZ"]

        self.assertNotEqual(
            mutated_snapshot["input_hash"],
            expected["selected_candidate"]["input_hash"],
        )
        self.assertNotEqual(_actual_golden(replay), expected)
        self.assertIsNotNone(replay.result.data.daily_pick)
        self.assertEqual(replay.result.data.daily_pick.ts_code, "000002.SZ")

    def _assert_no_future_labels(self, value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                lowered = str(key).lower()
                self.assertFalse(
                    any(token in lowered for token in FORBIDDEN_OUTPUT_TOKENS),
                    f"future label-like output key found: {key}",
                )
                self._assert_no_future_labels(item)
        elif isinstance(value, list):
            for item in value:
                self._assert_no_future_labels(item)


def _load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _run_fixture_replay(fixture: dict[str, Any]) -> _ReplayRun:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "pgc.db"
        run_migrations(db_path)
        seed_reference_data(db_path)
        with sqlite3.connect(db_path) as conn:
            _insert_fixture(conn, fixture)

        result = DailyReviewService(db_path).run_daily_review(
            RunDailyReviewRequest(
                as_of_date=fixture["review_date"],
                strategy_version=fixture["strategy_version"],
            ),
            RequestContext(
                request_id=f"replay:{fixture['case_id']}",
                idempotency_key=f"replay:{fixture['case_id']}",
                operator="replay-test",
            ),
        )
        if result.data is None or result.data.feature_run_id is None:
            raise AssertionError(f"replay did not create feature run: {result}")

        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            return _collect_replay_run(conn, result)


def _insert_fixture(conn: sqlite3.Connection, fixture: dict[str, Any]) -> None:
    conn.executemany(
        """
        INSERT INTO trade_calendar (exchange, cal_date, is_open, pretrade_date)
        VALUES ('SSE', ?, ?, ?)
        """,
        [
            (item["cal_date"], item["is_open"], item.get("pretrade_date"))
            for item in fixture["calendar"]
        ],
    )
    conn.executemany(
        """
        INSERT INTO raw_events
          (id, ts_code, code, name, entry_date, entry_time, entry_price, source, is_valid)
        VALUES
          (?, ?, ?, ?, ?, ?, ?, 'golden_replay', 1)
        """,
        [
            (
                item["id"],
                item["ts_code"],
                item.get("code"),
                item["name"],
                item["entry_date"],
                item.get("entry_time"),
                item["entry_price"],
            )
            for item in fixture["raw_events"]
        ],
    )
    for ts_code, bars in fixture["market_bars"].items():
        conn.executemany(
            """
            INSERT INTO market_bars
              (
                ts_code,
                trade_date,
                open,
                high,
                low,
                close,
                vol,
                amount,
                adj_open,
                adj_high,
                adj_low,
                adj_close,
                provider
              )
            VALUES
              (?, ?, ?, ?, ?, ?, 100000.0, ?, ?, ?, ?, ?, 'golden_replay')
            """,
            [
                (
                    ts_code,
                    bar["trade_date"],
                    bar["open"],
                    bar["high"],
                    bar["low"],
                    bar["close"],
                    bar["amount"],
                    bar["open"],
                    bar["high"],
                    bar["low"],
                    bar["close"],
                )
                for bar in bars
            ],
        )

    for snapshot in fixture["context_snapshots"]:
        cursor = conn.execute(
            """
            INSERT INTO feature_runs (feature_version, as_of_date, status)
            VALUES (?, ?, 'completed')
            """,
            (snapshot["feature_version"], snapshot["review_date"]),
        )
        conn.execute(
            """
            INSERT INTO feature_snapshots
              (
                feature_run_id,
                raw_event_id,
                ts_code,
                review_date,
                feature_version,
                features_json,
                input_hash
              )
            VALUES
              (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(cursor.lastrowid),
                snapshot["raw_event_id"],
                snapshot["ts_code"],
                snapshot["review_date"],
                snapshot["feature_version"],
                json.dumps(snapshot["features"], ensure_ascii=False, sort_keys=True),
                f"context:{snapshot['raw_event_id']}:{snapshot['review_date']}",
            ),
        )
    conn.commit()


def _collect_replay_run(conn: sqlite3.Connection, result: Any) -> _ReplayRun:
    data = result.data
    feature_run = _row_to_dict(
        conn.execute(
            """
            SELECT feature_version, as_of_date, status
            FROM feature_runs
            WHERE id = ?
            """,
            (data.feature_run_id,),
        ).fetchone()
    )
    snapshot_rows = conn.execute(
        """
        SELECT ts_code, review_date, feature_version, features_json, input_hash
        FROM feature_snapshots
        WHERE feature_run_id = ?
        ORDER BY ts_code
        """,
        (data.feature_run_id,),
    ).fetchall()
    signal_rows = conn.execute(
        """
        SELECT ts_code, signal_rank, signal_status, planned_buy_date, score
        FROM strategy_signals
        WHERE strategy_run_id = ?
        ORDER BY signal_rank
        """,
        (data.strategy_run_id,),
    ).fetchall()
    snapshots = {
        row["ts_code"]: {
            **_row_to_dict(row),
            "features": json.loads(row["features_json"]),
        }
        for row in snapshot_rows
    }
    return _ReplayRun(
        result=result,
        feature_run=feature_run,
        snapshots=snapshots,
        signals=[_row_to_dict(row) for row in signal_rows],
    )


def _actual_golden(replay: _ReplayRun) -> dict[str, Any]:
    data = replay.result.data
    pick = data.daily_pick
    if pick is None:
        selected_candidate = None
    else:
        selected_snapshot = replay.snapshots[pick.ts_code]
        selected_candidate = {
            "ts_code": pick.ts_code,
            "name": pick.name,
            "review_date": pick.review_date,
            "planned_buy_date": pick.planned_buy_date,
            "score": pick.score,
            "signal_rank": pick.signal_rank,
            "selection_reason": pick.selection_reason,
            "feature_version": selected_snapshot["feature_version"],
            "input_hash": selected_snapshot["input_hash"],
        }

    signals = []
    for signal in replay.signals:
        snapshot = replay.snapshots[signal["ts_code"]]
        features = snapshot["features"]
        signals.append(
            {
                "ts_code": signal["ts_code"],
                "signal_rank": signal["signal_rank"],
                "signal_status": signal["signal_status"],
                "planned_buy_date": signal["planned_buy_date"],
                "score": signal["score"],
                "feature_version": snapshot["feature_version"],
                "input_hash": snapshot["input_hash"],
                "latest_bar_date": features["latest_bar_date"],
                "context_source_review_date": features["cpb_v2_context_source_review_date"],
                "context_source_feature_version": features[
                    "cpb_v2_context_source_feature_version"
                ],
                "observation_sleeve": features["cpb_v2_observation_sleeve"],
                "short_sleeve_weight": features["cpb_v2_short_sleeve_weight"],
                "observation_sleeve_weight": features["cpb_v2_observation_sleeve_weight"],
            }
        )

    return {
        "status": replay.result.status,
        "signals_count": data.signals_count,
        "signals": signals,
        "selected_candidate": selected_candidate,
        "no_future_proof": {
            "feature_run_as_of_date": replay.feature_run["as_of_date"],
            "planned_buy_date": pick.planned_buy_date if pick else None,
            "latest_bar_date": selected_snapshot["features"]["latest_bar_date"] if pick else None,
            "context_source_review_date": selected_snapshot["features"][
                "cpb_v2_context_source_review_date"
            ]
            if pick
            else None,
            "snapshot_ts_codes": list(replay.snapshots),
            "signal_ts_codes": [signal["ts_code"] for signal in replay.signals],
            "forbidden_feature_tokens_absent": not _contains_forbidden_tokens(
                [snapshot["features"] for snapshot in replay.snapshots.values()]
            ),
        },
    }


def _contains_forbidden_tokens(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            any(token in str(key).lower() for token in FORBIDDEN_OUTPUT_TOKENS)
            or _contains_forbidden_tokens(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_tokens(item) for item in value)
    return False


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


if __name__ == "__main__":
    unittest.main()
