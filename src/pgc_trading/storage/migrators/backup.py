"""SQLite database backup helper."""

from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path


def backup_database(
    db_path: Path,
    backup_dir: Path | None = None,
    label: str = "before_migration",
) -> Path:
    """Copy a SQLite database to a timestamped backup file."""
    source = Path(db_path)
    if not source.exists():
        raise FileNotFoundError(f"Source database does not exist: {source}")
    if not source.is_file():
        raise ValueError(f"Source database path is not a file: {source}")

    target_dir = Path(backup_dir) if backup_dir is not None else source.parent / "backups"
    target_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    safe_label = _safe_label(label)
    target = target_dir / f"{source.stem}_{timestamp}_{safe_label}{source.suffix}"
    if target.exists():
        raise FileExistsError(f"Backup destination already exists: {target}")

    shutil.copy2(source, target)
    return target


def _safe_label(label: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", label).strip("_")
    return cleaned or "backup"
