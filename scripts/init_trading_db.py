#!/usr/bin/env python3
"""Initialize the PGC trading SQLite database."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pgc_trading.config import AccountConfig, Paths
from pgc_trading.storage.database import init_db, seed_account


def main() -> int:
    paths = Paths()
    db_path = init_db(paths.db_path)
    account_id = seed_account(AccountConfig(), db_path)
    print(json.dumps({"db_path": str(db_path), "account_id": account_id}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
