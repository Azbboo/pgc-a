"""Configuration for the PGC HTTP API adapter."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from pgc_trading.config import Paths


_TRUE_VALUES = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ApiSettings:
    db_path: Path
    enable_writes: bool = False
    write_token: str | None = None

    @classmethod
    def from_env(cls) -> "ApiSettings":
        paths = Paths()
        write_token = os.environ.get("PGC_API_WRITE_TOKEN", "").strip()
        return cls(
            db_path=Path(os.environ.get("PGC_DB_PATH", paths.db_path)),
            enable_writes=os.environ.get("PGC_API_ENABLE_WRITES", "").strip().lower() in _TRUE_VALUES,
            write_token=write_token or None,
        )
