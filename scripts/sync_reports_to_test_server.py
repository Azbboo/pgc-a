#!/usr/bin/env python3
"""Sync selected derived PGC reports to optional test-server targets.

SQLite remains the canonical local store. MySQL and Redis are integration
targets for test-server validation only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence, TextIO


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_JSON = ROOT / "reports" / "live_trade_plan.json"
MYSQL_ENV_KEYS = (
    "PGC_TEST_MYSQL_HOST",
    "PGC_TEST_MYSQL_DATABASE",
    "PGC_TEST_MYSQL_USER",
    "PGC_TEST_MYSQL_PASSWORD",
)
REDIS_ENV_KEYS = (
    "PGC_TEST_REDIS_HOST",
    "PGC_TEST_REDIS_PORT",
)
REQUIRED_ENV_KEYS = MYSQL_ENV_KEYS + REDIS_ENV_KEYS


class SyncConfigurationError(RuntimeError):
    """Raised when required runtime-only sync configuration is missing."""


class SyncRuntimeError(RuntimeError):
    """Raised when a report cannot be prepared or a target cannot be reached."""


@dataclass(frozen=True)
class TestServerSyncConfig:
    mysql_host: str
    mysql_database: str
    mysql_user: str
    mysql_password: str
    redis_host: str
    redis_port: int
    redis_password: str | None = None

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        targets: Sequence[str] = ("mysql", "redis"),
    ) -> "TestServerSyncConfig":
        source = os.environ if env is None else env
        normalized_targets = normalize_targets(targets)
        required = []
        if "mysql" in normalized_targets:
            required.extend(MYSQL_ENV_KEYS)
        if "redis" in normalized_targets:
            required.extend(REDIS_ENV_KEYS)

        missing = [key for key in required if not source.get(key, "").strip()]
        if missing:
            raise SyncConfigurationError(
                "Missing required test-server sync env vars: "
                + ", ".join(missing)
                + ". Export them locally or put them in ignored .env.test-server; "
                + "do not commit real server, MySQL, or Redis secrets."
            )

        redis_port = (
            _parse_port(source["PGC_TEST_REDIS_PORT"].strip())
            if "redis" in normalized_targets
            else 0
        )
        redis_password = source.get("PGC_TEST_REDIS_PASSWORD", "").strip() or None
        return cls(
            mysql_host=source.get("PGC_TEST_MYSQL_HOST", "").strip(),
            mysql_database=source.get("PGC_TEST_MYSQL_DATABASE", "").strip(),
            mysql_user=source.get("PGC_TEST_MYSQL_USER", "").strip(),
            mysql_password=source.get("PGC_TEST_MYSQL_PASSWORD", "").strip(),
            redis_host=source.get("PGC_TEST_REDIS_HOST", "").strip(),
            redis_port=redis_port,
            redis_password=redis_password,
        )

    def __repr__(self) -> str:
        return (
            "TestServerSyncConfig("
            f"mysql_host={self.mysql_host!r}, "
            f"mysql_database={self.mysql_database!r}, "
            f"redis_host={self.redis_host!r}, "
            f"redis_port={self.redis_port!r}, "
            "secrets=<redacted>)"
        )

    def public_targets(self, targets: Sequence[str]) -> dict[str, dict[str, Any]]:
        public: dict[str, dict[str, Any]] = {}
        if "mysql" in targets:
            public["mysql"] = {
                "host": self.mysql_host,
                "database": self.mysql_database,
            }
        if "redis" in targets:
            public["redis"] = {
                "host": self.redis_host,
                "port": self.redis_port,
            }
        return public


@dataclass(frozen=True)
class ReportArtifact:
    artifact_type: str
    source_path: str
    content_hash: str
    payload_json: str

    @property
    def redis_hash_key(self) -> str:
        return f"pgc:test-server-sync:{self.artifact_type}:{self.content_hash}"

    @property
    def redis_latest_key(self) -> str:
        return f"pgc:test-server-sync:{self.artifact_type}:latest"

    def public_summary(self) -> dict[str, str]:
        return {
            "artifact_type": self.artifact_type,
            "source_path": self.source_path,
            "content_hash": self.content_hash,
        }


class PyMySqlReportClient:
    """Tiny MySQL sink wrapper kept optional for the POC."""

    def __init__(self, config: TestServerSyncConfig):
        try:
            import pymysql  # type: ignore[import-not-found]
        except ImportError as exc:
            raise SyncRuntimeError(
                "pymysql is required for real MySQL sync. Install it locally or run with --dry-run."
            ) from exc

        self._connection = pymysql.connect(
            host=config.mysql_host,
            user=config.mysql_user,
            password=config.mysql_password,
            database=config.mysql_database,
            charset="utf8mb4",
            autocommit=False,
        )

    def upsert_report_artifact(self, artifact: ReportArtifact) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS pgc_report_sync_artifacts (
                  id BIGINT AUTO_INCREMENT PRIMARY KEY,
                  artifact_type VARCHAR(64) NOT NULL,
                  content_hash CHAR(64) NOT NULL,
                  source_path VARCHAR(512) NOT NULL,
                  payload_json JSON NOT NULL,
                  synced_from VARCHAR(64) NOT NULL,
                  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                  UNIQUE KEY uq_pgc_report_sync_artifacts (artifact_type, content_hash)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            cursor.execute(
                """
                INSERT INTO pgc_report_sync_artifacts
                  (artifact_type, content_hash, source_path, payload_json, synced_from)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                  source_path = VALUES(source_path),
                  payload_json = VALUES(payload_json),
                  synced_from = VALUES(synced_from),
                  updated_at = CURRENT_TIMESTAMP
                """,
                (
                    artifact.artifact_type,
                    artifact.content_hash,
                    artifact.source_path,
                    artifact.payload_json,
                    "pgc-local-sqlite",
                ),
            )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()


class RedisReportClient:
    """Tiny Redis sink wrapper kept optional for the POC."""

    def __init__(self, config: TestServerSyncConfig):
        try:
            import redis  # type: ignore[import-not-found]
        except ImportError as exc:
            raise SyncRuntimeError(
                "redis is required for real Redis sync. Install it locally or run with --dry-run."
            ) from exc

        self._client = redis.Redis(
            host=config.redis_host,
            port=config.redis_port,
            password=config.redis_password,
            decode_responses=True,
        )

    def publish_report_artifact(self, artifact: ReportArtifact) -> None:
        value = json.dumps(
            {
                "artifact_type": artifact.artifact_type,
                "content_hash": artifact.content_hash,
                "source_path": artifact.source_path,
                "payload_json": artifact.payload_json,
                "canonical_store": "local_sqlite",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        self._client.set(artifact.redis_hash_key, value)
        self._client.set(artifact.redis_latest_key, artifact.content_hash)

    def close(self) -> None:
        self._client.close()


def load_report_artifact(report_json: Path, artifact_type: str = "daily_report") -> ReportArtifact:
    path = report_json.expanduser()
    if not path.exists():
        raise SyncRuntimeError(
            f"Report JSON not found: {path}. Generate the report first or pass --report-json."
        )
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SyncRuntimeError(f"Report JSON is invalid: {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise SyncRuntimeError(f"Report JSON must contain an object: {path}")

    payload_json = json.dumps(loaded, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    content_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    return ReportArtifact(
        artifact_type=artifact_type,
        source_path=str(path),
        content_hash=content_hash,
        payload_json=payload_json,
    )


def sync_report_artifact(
    artifact: ReportArtifact,
    config: TestServerSyncConfig,
    *,
    targets: Sequence[str],
    dry_run: bool,
    mysql_client: Any | None = None,
    redis_client: Any | None = None,
) -> dict[str, Any]:
    normalized_targets = normalize_targets(targets)
    result: dict[str, Any] = {
        "status": "planned" if dry_run else "synced",
        "dry_run": dry_run,
        "canonical_store": "local_sqlite",
        "artifact": artifact.public_summary(),
        "targets": config.public_targets(normalized_targets),
        "actions": [],
    }
    if dry_run:
        result["actions"] = [f"would_sync_{target}" for target in normalized_targets]
        return result

    owned_mysql_client = None
    owned_redis_client = None
    try:
        if "mysql" in normalized_targets:
            client = mysql_client
            if client is None:
                owned_mysql_client = PyMySqlReportClient(config)
                client = owned_mysql_client
            client.upsert_report_artifact(artifact)
            result["actions"].append("synced_mysql")

        if "redis" in normalized_targets:
            client = redis_client
            if client is None:
                owned_redis_client = RedisReportClient(config)
                client = owned_redis_client
            client.publish_report_artifact(artifact)
            result["actions"].append("synced_redis")
    finally:
        if owned_mysql_client is not None:
            owned_mysql_client.close()
        if owned_redis_client is not None:
            owned_redis_client.close()

    return result


def normalize_targets(targets: Sequence[str]) -> tuple[str, ...]:
    expanded: list[str] = []
    for target in targets:
        if target == "both":
            expanded.extend(["mysql", "redis"])
        elif target in {"mysql", "redis"}:
            expanded.append(target)
        else:
            raise SyncConfigurationError(f"Unsupported sync target: {target}")

    unique = tuple(dict.fromkeys(expanded))
    if not unique:
        raise SyncConfigurationError("At least one sync target is required.")
    return unique


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report-json",
        type=Path,
        default=DEFAULT_REPORT_JSON,
        help="derived report JSON artifact to sync",
    )
    parser.add_argument(
        "--target",
        action="append",
        choices=["mysql", "redis", "both"],
        default=None,
        help="sync target; repeat for multiple targets; defaults to both",
    )
    parser.add_argument("--dry-run", action="store_true", help="print planned public targets only")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    env: Mapping[str, str] | None = None,
    mysql_client: Any | None = None,
    redis_client: Any | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    targets = normalize_targets(args.target or ["both"])

    try:
        config = TestServerSyncConfig.from_env(env, targets=targets)
        artifact = load_report_artifact(args.report_json)
        result = sync_report_artifact(
            artifact,
            config,
            targets=targets,
            dry_run=args.dry_run,
            mysql_client=mysql_client,
            redis_client=redis_client,
        )
    except SyncConfigurationError as exc:
        print(f"configuration error: {exc}", file=stderr)
        return 2
    except SyncRuntimeError as exc:
        print(f"sync error: {exc}", file=stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), file=stdout)
    return 0


def _parse_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise SyncConfigurationError(
            "PGC_TEST_REDIS_PORT must be an integer between 1 and 65535."
        ) from exc
    if port < 1 or port > 65535:
        raise SyncConfigurationError("PGC_TEST_REDIS_PORT must be between 1 and 65535.")
    return port


if __name__ == "__main__":
    raise SystemExit(main())
