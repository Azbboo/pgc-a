"""Reference data seeding for the target trading store."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from pgc_trading.config import AccountConfig, Paths
from pgc_trading.storage.migrate import connect_for_migration
from pgc_trading.strategies.cpb_6157 import (
    PARAMS as CPB_6157_PARAMS,
    PARAMS_HASH as CPB_6157_PARAMS_HASH,
    STRATEGY_KEY as CPB_6157_STRATEGY_KEY,
    STRATEGY_VERSION as CPB_6157_STRATEGY_VERSION,
)
from pgc_trading.strategies.cpb_v2 import (
    PARAMS as CPB_V2_PARAMS,
    PARAMS_HASH as CPB_V2_PARAMS_HASH,
    STRATEGY_KEY as CPB_V2_STRATEGY_KEY,
    STRATEGY_VERSION as CPB_V2_STRATEGY_VERSION,
)


STRATEGY_FAMILY_KEY = "contracting_pullback"
STRATEGY_FAMILY_NAME = "Contracting Pullback"
STRATEGY_FAMILY_DESCRIPTION = (
    "PGC pool contraction pullback with bullish-candle confirmation."
)
DEFAULT_LIVE_ACCOUNT = AccountConfig(
    account_key="live-main",
    name="Live Main",
    account_type="live",
    initial_cash=200000.0,
    max_positions=3,
    position_sizing="equal_slots",
    status="active",
)


@dataclass(frozen=True)
class ReferenceSeedResult:
    db_path: Path
    ids: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "db_path": str(self.db_path),
            "ids": self.ids,
        }


def seed_reference_data(
    db_path: Path | None = None,
    account_config: AccountConfig | None = None,
) -> ReferenceSeedResult:
    """Seed idempotent reference rows required after DDL migrations."""

    path = db_path or Paths().db_path
    with connect_for_migration(path) as conn:
        family_id = _seed_strategy_family(conn)
        cpb_6157_version_id = _seed_strategy_version(
            conn,
            family_id,
            strategy_key=CPB_6157_STRATEGY_KEY,
            strategy_version=CPB_6157_STRATEGY_VERSION,
            params_hash=CPB_6157_PARAMS_HASH,
            status="paper",
        )
        cpb_6157_parameter_set_id = _seed_parameter_set(
            conn,
            cpb_6157_version_id,
            CPB_6157_PARAMS.canonical_json(),
            CPB_6157_PARAMS_HASH,
        )
        cpb_v2_version_id = _seed_strategy_version(
            conn,
            family_id,
            strategy_key=CPB_V2_STRATEGY_KEY,
            strategy_version=CPB_V2_STRATEGY_VERSION,
            params_hash=CPB_V2_PARAMS_HASH,
            status="candidate",
        )
        cpb_v2_parameter_set_id = _seed_parameter_set(
            conn,
            cpb_v2_version_id,
            CPB_V2_PARAMS.canonical_json(),
            CPB_V2_PARAMS_HASH,
        )
        account_ids, account_result_ids = _seed_account_catalog(conn, account_config)

    return ReferenceSeedResult(
        db_path=path,
        ids={
            "strategy_family": family_id,
            "strategy_version": cpb_6157_version_id,
            "parameter_set": cpb_6157_parameter_set_id,
            "strategy_version_cpb_6157": cpb_6157_version_id,
            "parameter_set_cpb_6157": cpb_6157_parameter_set_id,
            "strategy_version_cpb_v2": cpb_v2_version_id,
            "parameter_set_cpb_v2": cpb_v2_parameter_set_id,
            "portfolio_account": account_ids["paper-main"],
            **account_result_ids,
        },
    )


def _seed_strategy_family(conn: sqlite3.Connection) -> int:
    conn.execute(
        """
        INSERT INTO strategy_families
          (family_key, name, description, owner, status)
        VALUES
          (?, ?, ?, 'azboo', 'active')
        ON CONFLICT(family_key) DO UPDATE SET
          name = excluded.name,
          description = excluded.description,
          owner = excluded.owner,
          status = excluded.status
        """,
        (STRATEGY_FAMILY_KEY, STRATEGY_FAMILY_NAME, STRATEGY_FAMILY_DESCRIPTION),
    )
    return _single_id(
        conn,
        "SELECT id FROM strategy_families WHERE family_key = ?",
        (STRATEGY_FAMILY_KEY,),
    )


def _seed_strategy_version(
    conn: sqlite3.Connection,
    family_id: int,
    *,
    strategy_key: str,
    strategy_version: str,
    params_hash: str,
    status: str,
) -> int:
    conn.execute(
        """
        INSERT INTO strategy_versions
          (
            strategy_family_id,
            strategy_key,
            strategy_version,
            code_version,
            params_hash,
            entry_policy_id,
            exit_policy_id,
            position_policy_id,
            agent_policy,
            status
          )
        VALUES
          (
            ?,
            ?,
            ?,
            'local',
            ?,
            'contracting_pullback_bull_confirm',
            't2_3pct_t5_timeout',
            'equal_slots_max3',
            'advisory',
            ?
          )
        ON CONFLICT(strategy_version) DO UPDATE SET
          strategy_family_id = excluded.strategy_family_id,
          strategy_key = excluded.strategy_key,
          code_version = excluded.code_version,
          params_hash = excluded.params_hash,
          entry_policy_id = excluded.entry_policy_id,
          exit_policy_id = excluded.exit_policy_id,
          position_policy_id = excluded.position_policy_id,
          agent_policy = excluded.agent_policy,
          status = excluded.status
        """,
        (family_id, strategy_key, strategy_version, params_hash, status),
    )
    return _single_id(
        conn,
        "SELECT id FROM strategy_versions WHERE strategy_version = ?",
        (strategy_version,),
    )


def _seed_parameter_set(
    conn: sqlite3.Connection,
    version_id: int,
    params_json: str,
    params_hash: str,
) -> int:
    conn.execute(
        """
        INSERT INTO parameter_sets
          (strategy_version_id, params_json, params_hash)
        VALUES
          (?, ?, ?)
        ON CONFLICT(strategy_version_id, params_hash) DO UPDATE SET
          params_json = excluded.params_json
        """,
        (version_id, params_json, params_hash),
    )
    return _single_id(
        conn,
        """
        SELECT id FROM parameter_sets
        WHERE strategy_version_id = ? AND params_hash = ?
        """,
        (version_id, params_hash),
    )


def _seed_account_catalog(
    conn: sqlite3.Connection,
    account_config: AccountConfig | None,
) -> tuple[dict[str, int], dict[str, int]]:
    accounts = {
        _account_key(AccountConfig()): AccountConfig(),
        _account_key(DEFAULT_LIVE_ACCOUNT): DEFAULT_LIVE_ACCOUNT,
    }
    if account_config is not None:
        accounts[_account_key(account_config)] = account_config

    account_ids: dict[str, int] = {}
    result_ids: dict[str, int] = {}
    for account in accounts.values():
        account_key = _account_key(account)
        account_id = _seed_portfolio_account(conn, account)
        account_ids[account_key] = account_id
        result_ids[f"portfolio_account_{_result_key(account_key)}"] = account_id
    return account_ids, result_ids


def _seed_portfolio_account(conn: sqlite3.Connection, account: AccountConfig) -> int:
    account_key = _account_key(account)
    conn.execute(
        """
        INSERT INTO portfolio_accounts
          (
            account_key,
            name,
            account_type,
            initial_cash,
            max_positions,
            position_sizing,
            status
          )
        VALUES
          (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(account_key) DO UPDATE SET
          name = excluded.name,
          account_type = excluded.account_type,
          initial_cash = excluded.initial_cash,
          max_positions = excluded.max_positions,
          position_sizing = excluded.position_sizing,
          status = excluded.status
        """,
        (
            account_key,
            account.name,
            account.account_type,
            account.initial_cash,
            account.max_positions,
            account.position_sizing,
            account.status,
        ),
    )
    return _single_id(
        conn,
        "SELECT id FROM portfolio_accounts WHERE account_key = ?",
        (account_key,),
    )


def _account_key(account: AccountConfig) -> str:
    if account.account_key:
        return str(account.account_key)

    slug = re.sub(r"[^a-z0-9]+", "-", account.name.lower()).strip("-")
    if not slug:
        return f"{account.account_type}-account"
    if slug == account.account_type or slug.startswith(f"{account.account_type}-"):
        return slug
    return f"{account.account_type}-{slug}"


def _result_key(account_key: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", account_key.lower()).strip("_")
    return slug or "account"


def _single_id(
    conn: sqlite3.Connection,
    query: str,
    params: tuple[object, ...],
) -> int:
    row = conn.execute(query, params).fetchone()
    if row is None:
        raise RuntimeError(f"Seed row was not found after upsert: {query.strip()}")
    return int(row[0])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed PGC reference data.")
    parser.add_argument("--db-path", type=Path, default=Paths().db_path)
    args = parser.parse_args(argv)

    result = seed_reference_data(args.db_path)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
