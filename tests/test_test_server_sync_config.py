from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "sync_reports_to_test_server.py"
SPEC = importlib.util.spec_from_file_location("sync_reports_to_test_server", SCRIPT_PATH)
sync_module = importlib.util.module_from_spec(SPEC)
sys.modules["sync_reports_to_test_server"] = sync_module
assert SPEC.loader is not None
SPEC.loader.exec_module(sync_module)


class TestServerSyncConfigTest(unittest.TestCase):
    def test_missing_env_vars_fail_with_clear_instructions(self) -> None:
        with self.assertRaises(sync_module.SyncConfigurationError) as caught:
            sync_module.TestServerSyncConfig.from_env({})

        message = str(caught.exception)
        for key in sync_module.REQUIRED_ENV_KEYS:
            self.assertIn(key, message)
        self.assertIn(".env.test-server", message)
        self.assertIn("do not commit", message)

    def test_invalid_redis_port_fails_before_any_client_is_built(self) -> None:
        env = _complete_env()
        env["PGC_TEST_REDIS_PORT"] = "not-a-port"

        with self.assertRaises(sync_module.SyncConfigurationError) as caught:
            sync_module.TestServerSyncConfig.from_env(env)

        self.assertIn("PGC_TEST_REDIS_PORT", str(caught.exception))

    def test_dry_run_prints_public_targets_without_passwords_or_client_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_path = _write_report(tmp)
            stdout = io.StringIO()
            stderr = io.StringIO()

            code = sync_module.main(
                ["--dry-run", "--report-json", str(report_path)],
                stdout=stdout,
                stderr=stderr,
                env=_complete_env(),
                mysql_client=_UnexpectedMysqlClient(),
                redis_client=_UnexpectedRedisClient(),
            )

        self.assertEqual(code, 0, stderr.getvalue())
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["status"], "planned")
        self.assertEqual(payload["canonical_store"], "local_sqlite")
        self.assertEqual(payload["targets"]["mysql"]["host"], "mysql.test.local")
        self.assertEqual(payload["targets"]["mysql"]["database"], "pgc_test_db")
        self.assertEqual(payload["targets"]["redis"]["host"], "redis.test.local")
        self.assertNotIn("<fake-mysql-secret>", stdout.getvalue())
        self.assertNotIn("<fake-redis-secret>", stdout.getvalue())

    def test_sync_uses_fake_clients_without_real_network(self) -> None:
        mysql_client = _FakeMysqlClient()
        redis_client = _FakeRedisClient()

        with tempfile.TemporaryDirectory() as tmp:
            report_path = _write_report(tmp)
            stdout = io.StringIO()
            stderr = io.StringIO()
            code = sync_module.main(
                ["--report-json", str(report_path)],
                stdout=stdout,
                stderr=stderr,
                env=_complete_env(),
                mysql_client=mysql_client,
                redis_client=redis_client,
            )

        self.assertEqual(code, 0, stderr.getvalue())
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "synced")
        self.assertEqual(payload["actions"], ["synced_mysql", "synced_redis"])
        self.assertEqual(len(mysql_client.artifacts), 1)
        self.assertEqual(len(redis_client.artifacts), 1)
        self.assertEqual(mysql_client.artifacts[0].content_hash, redis_client.artifacts[0].content_hash)

    def test_mysql_only_target_does_not_touch_redis_client(self) -> None:
        mysql_client = _FakeMysqlClient()

        with tempfile.TemporaryDirectory() as tmp:
            report_path = _write_report(tmp)
            stdout = io.StringIO()
            stderr = io.StringIO()
            code = sync_module.main(
                ["--target", "mysql", "--report-json", str(report_path)],
                stdout=stdout,
                stderr=stderr,
                env=_complete_env(),
                mysql_client=mysql_client,
                redis_client=_UnexpectedRedisClient(),
            )

        self.assertEqual(code, 0, stderr.getvalue())
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["actions"], ["synced_mysql"])
        self.assertEqual(set(payload["targets"]), {"mysql"})

    def test_mysql_only_target_requires_only_mysql_env(self) -> None:
        mysql_client = _FakeMysqlClient()
        env = {
            "PGC_TEST_MYSQL_HOST": "mysql.test.local",
            "PGC_TEST_MYSQL_DATABASE": "pgc_test_db",
            "PGC_TEST_MYSQL_USER": "pgc_user",
            "PGC_TEST_MYSQL_PASSWORD": "<fake-mysql-secret>",
        }

        with tempfile.TemporaryDirectory() as tmp:
            report_path = _write_report(tmp)
            stdout = io.StringIO()
            stderr = io.StringIO()
            code = sync_module.main(
                ["--target", "mysql", "--report-json", str(report_path)],
                stdout=stdout,
                stderr=stderr,
                env=env,
                mysql_client=mysql_client,
            )

        self.assertEqual(code, 0, stderr.getvalue())
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["actions"], ["synced_mysql"])
        self.assertEqual(set(payload["targets"]), {"mysql"})


class _FakeMysqlClient:
    def __init__(self) -> None:
        self.artifacts = []

    def upsert_report_artifact(self, artifact) -> None:
        self.artifacts.append(artifact)


class _FakeRedisClient:
    def __init__(self) -> None:
        self.artifacts = []

    def publish_report_artifact(self, artifact) -> None:
        self.artifacts.append(artifact)


class _UnexpectedMysqlClient:
    def upsert_report_artifact(self, artifact) -> None:
        raise AssertionError("dry-run should not call MySQL client")


class _UnexpectedRedisClient:
    def publish_report_artifact(self, artifact) -> None:
        raise AssertionError("this test should not call Redis client")


def _complete_env() -> dict[str, str]:
    return {
        "PGC_TEST_MYSQL_HOST": "mysql.test.local",
        "PGC_TEST_MYSQL_DATABASE": "pgc_test_db",
        "PGC_TEST_MYSQL_USER": "pgc_user",
        "PGC_TEST_MYSQL_PASSWORD": "<fake-mysql-secret>",
        "PGC_TEST_REDIS_HOST": "redis.test.local",
        "PGC_TEST_REDIS_PORT": "6379",
        "PGC_TEST_REDIS_PASSWORD": "<fake-redis-secret>",
    }


def _write_report(tmp: str) -> Path:
    report_path = Path(tmp) / "daily_report.json"
    report_path.write_text(
        json.dumps(
            {
                "as_of_date": "20260506",
                "candidate": {"ts_code": "000001.SZ", "score": 91},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return report_path


if __name__ == "__main__":
    unittest.main()
