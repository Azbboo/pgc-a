from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pgc_trading.config import AccountConfig
from pgc_trading.storage.migrate import run_migrations
from pgc_trading.storage.seed import seed_reference_data
from pgc_trading.strategies.cpb_6157 import PARAMS_HASH
from pgc_trading.strategies.cpb_v2 import PARAMS_HASH as CPB_V2_PARAMS_HASH


class ReferenceSeedTest(unittest.TestCase):
    def test_reference_seed_writes_expected_strategy_and_account(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            run_migrations(db_path)

            account = AccountConfig(
                name="Configured Paper Account",
                initial_cash=123456.0,
                max_positions=4,
                position_sizing="equal_slots",
            )

            result = seed_reference_data(db_path, account)

            with sqlite3.connect(db_path) as conn:
                conn.execute("PRAGMA foreign_keys = ON")

                family = conn.execute(
                    """
                    SELECT id, family_key, status
                    FROM strategy_families
                    WHERE family_key = 'contracting_pullback'
                    """
                ).fetchone()
                self.assertIsNotNone(family)
                self.assertEqual(family[0], result.ids["strategy_family"])
                self.assertEqual(family[1], "contracting_pullback")
                self.assertEqual(family[2], "active")

                version = conn.execute(
                    """
                    SELECT
                      id,
                      strategy_family_id,
                      strategy_key,
                      strategy_version,
                      params_hash,
                      agent_policy,
                      status
                    FROM strategy_versions
                    WHERE strategy_version = 'cpb_6157@2026-05-03'
                    """
                ).fetchone()
                self.assertIsNotNone(version)
                self.assertEqual(version[0], result.ids["strategy_version"])
                self.assertEqual(version[1], family[0])
                self.assertEqual(version[2], "cpb_6157")
                self.assertEqual(version[3], "cpb_6157@2026-05-03")
                self.assertEqual(version[4], PARAMS_HASH)
                self.assertEqual(version[5], "advisory")
                self.assertEqual(version[6], "paper")

                parameter_set = conn.execute(
                    """
                    SELECT id, strategy_version_id, params_json, params_hash
                    FROM parameter_sets
                    WHERE strategy_version_id = ?
                    """,
                    (version[0],),
                ).fetchone()
                self.assertIsNotNone(parameter_set)
                self.assertEqual(parameter_set[0], result.ids["parameter_set"])
                self.assertEqual(parameter_set[1], version[0])
                self.assertEqual(parameter_set[3], PARAMS_HASH)
                self.assertEqual(json.loads(parameter_set[2])["variant_id"], "cpb_6157")

                v2_version = conn.execute(
                    """
                    SELECT
                      id,
                      strategy_family_id,
                      strategy_key,
                      strategy_version,
                      params_hash,
                      agent_policy,
                      status
                    FROM strategy_versions
                    WHERE strategy_version = 'cpb_v2@2026-05-06'
                    """
                ).fetchone()
                self.assertIsNotNone(v2_version)
                self.assertEqual(v2_version[0], result.ids["strategy_version_cpb_v2"])
                self.assertEqual(v2_version[1], family[0])
                self.assertEqual(v2_version[2], "cpb_v2")
                self.assertEqual(v2_version[3], "cpb_v2@2026-05-06")
                self.assertEqual(v2_version[4], CPB_V2_PARAMS_HASH)
                self.assertEqual(v2_version[5], "advisory")
                self.assertEqual(v2_version[6], "candidate")

                v2_parameter_set = conn.execute(
                    """
                    SELECT id, strategy_version_id, params_json, params_hash
                    FROM parameter_sets
                    WHERE strategy_version_id = ?
                    """,
                    (v2_version[0],),
                ).fetchone()
                self.assertIsNotNone(v2_parameter_set)
                self.assertEqual(v2_parameter_set[0], result.ids["parameter_set_cpb_v2"])
                self.assertEqual(v2_parameter_set[1], v2_version[0])
                self.assertEqual(v2_parameter_set[3], CPB_V2_PARAMS_HASH)
                self.assertEqual(json.loads(v2_parameter_set[2])["variant_id"], "cpb_v2")

                account_row = conn.execute(
                    """
                    SELECT
                      id,
                      account_key,
                      name,
                      account_type,
                      initial_cash,
                      max_positions,
                      position_sizing,
                      status
                    FROM portfolio_accounts
                    """
                ).fetchone()
                self.assertIsNotNone(account_row)
                self.assertEqual(account_row[0], result.ids["portfolio_account"])
                self.assertEqual(account_row[1], "paper-configured-paper-account")
                self.assertEqual(account_row[2], account.name)
                self.assertEqual(account_row[3], "paper")
                self.assertEqual(account_row[4], account.initial_cash)
                self.assertEqual(account_row[5], account.max_positions)
                self.assertEqual(account_row[6], account.position_sizing)
                self.assertEqual(account_row[7], "active")

                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*) FROM portfolio_accounts WHERE account_type = 'live'"
                    ).fetchone()[0],
                    0,
                )
                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_reference_seed_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pgc.db"
            run_migrations(db_path)
            account = AccountConfig(name="paper_200k")

            first = seed_reference_data(db_path, account)
            second = seed_reference_data(db_path, account)

            self.assertEqual(first.ids, second.ids)
            with sqlite3.connect(db_path) as conn:
                counts = {
                    table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in (
                        "strategy_families",
                        "strategy_versions",
                        "parameter_sets",
                        "portfolio_accounts",
                    )
                }

            self.assertEqual(
                counts,
                {
                    "strategy_families": 1,
                    "strategy_versions": 2,
                    "parameter_sets": 2,
                    "portfolio_accounts": 1,
                },
            )


if __name__ == "__main__":
    unittest.main()
