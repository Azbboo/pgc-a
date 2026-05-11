from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path

from pgc_trading.api import ApiDependencyError, create_app
from pgc_trading.api.errors import service_result_http_status
from pgc_trading.api.schemas import build_health_payload, service_result_envelope
from pgc_trading.api.settings import ApiSettings
from pgc_trading.services.common import ServiceError, ServiceResult


class ApiAppTest(unittest.TestCase):
    def test_api_package_imports_without_fastapi_dependency(self) -> None:
        self.assertTrue(callable(create_app))

    def test_create_app_reports_missing_optional_dependency(self) -> None:
        if importlib.util.find_spec("fastapi") is not None:
            self.skipTest("FastAPI is installed in this environment")

        with self.assertRaises(ApiDependencyError) as raised:
            create_app(ApiSettings(db_path=Path("/tmp/pgc.db")))

        self.assertIn("python3 -m pip install -e '.[api]'", str(raised.exception))

    def test_health_payload_is_stable_and_non_sensitive(self) -> None:
        payload = build_health_payload(
            ApiSettings(
                db_path=Path("/tmp/pgc-secret-name.db"),
                enable_writes=False,
                write_token="secret-write-token",
            )
        )

        self.assertEqual(
            payload,
            {
                "status": "ok",
                "service": "pgc-trading-api",
                "api_version": "0.1.0",
                "writes_enabled": False,
                "database_configured": True,
            },
        )
        self.assertNotIn("pgc-secret-name", repr(payload))
        self.assertNotIn("secret-write-token", repr(payload))
        self.assertFalse(any("token" in key for key in payload))

    def test_api_settings_reads_write_token_from_environment_without_exposing_it(self) -> None:
        old_db_path = os.environ.get("PGC_DB_PATH")
        old_enable_writes = os.environ.get("PGC_API_ENABLE_WRITES")
        old_write_token = os.environ.get("PGC_API_WRITE_TOKEN")
        try:
            os.environ["PGC_DB_PATH"] = "/tmp/pgc-env.db"
            os.environ["PGC_API_ENABLE_WRITES"] = "1"
            os.environ["PGC_API_WRITE_TOKEN"] = " env-secret-token "

            settings = ApiSettings.from_env()
        finally:
            if old_db_path is None:
                os.environ.pop("PGC_DB_PATH", None)
            else:
                os.environ["PGC_DB_PATH"] = old_db_path
            if old_enable_writes is None:
                os.environ.pop("PGC_API_ENABLE_WRITES", None)
            else:
                os.environ["PGC_API_ENABLE_WRITES"] = old_enable_writes
            if old_write_token is None:
                os.environ.pop("PGC_API_WRITE_TOKEN", None)
            else:
                os.environ["PGC_API_WRITE_TOKEN"] = old_write_token

        self.assertEqual(settings.db_path, Path("/tmp/pgc-env.db"))
        self.assertTrue(settings.enable_writes)
        self.assertEqual(settings.write_token, "env-secret-token")
        self.assertNotIn("env-secret-token", repr(build_health_payload(settings)))

    def test_create_app_registers_health_when_fastapi_is_available(self) -> None:
        if importlib.util.find_spec("fastapi") is None:
            self.skipTest("FastAPI is not installed in this environment")

        app = create_app(ApiSettings(db_path=Path("/tmp/pgc.db"), enable_writes=True))
        health_route = next(route for route in app.routes if route.path == "/api/health")
        payload = health_route.endpoint()

        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["writes_enabled"])

    def test_openapi_schema_builds_when_fastapi_is_available(self) -> None:
        if importlib.util.find_spec("fastapi") is None:
            self.skipTest("FastAPI is not installed in this environment")

        app = create_app(ApiSettings(db_path=Path("/tmp/pgc.db"), enable_writes=False))
        schema = app.openapi()

        self.assertIn("/api/health", schema["paths"])
        self.assertIn("/api/daily-reviews", schema["paths"])
        self.assertIn("/api/daily-reviews/{as_of_date}", schema["paths"])
        self.assertIn("/api/paper-acceptance/{as_of_date}", schema["paths"])
        self.assertIn("/api/paper-acceptance-history", schema["paths"])
        self.assertIn("/api/next-day-decision-cockpit/{as_of_date}", schema["paths"])
        self.assertIn("/api/market-reviews", schema["paths"])
        self.assertIn("/api/market-reviews/{as_of_date}", schema["paths"])
        self.assertIn("/api/market-reviews/{as_of_date}/sectors", schema["paths"])
        self.assertIn("/api/market-reviews/{as_of_date}/external-items", schema["paths"])
        self.assertIn("/api/market-reviews/{as_of_date}/hypotheses", schema["paths"])
        self.assertIn("/api/market-reviews/{as_of_date}/plan-context", schema["paths"])
        market_review_paths = [
            "/api/market-reviews",
            "/api/market-reviews/{as_of_date}",
            "/api/market-reviews/{as_of_date}/sectors",
            "/api/market-reviews/{as_of_date}/external-items",
            "/api/market-reviews/{as_of_date}/hypotheses",
            "/api/market-reviews/{as_of_date}/plan-context",
        ]
        for path in market_review_paths:
            self.assertEqual(set(schema["paths"][path]), {"get"})

    def test_service_result_envelope_preserves_contract_shape(self) -> None:
        result = ServiceResult(
            status="validation_failed",
            request_id="req-1",
            data={"field": "value"},
            errors=[ServiceError(code="VALIDATION_ERROR", message="bad input")],
            lineage={"account_id": 1},
        )

        self.assertEqual(service_result_http_status(result), 400)
        self.assertEqual(
            service_result_envelope(result),
            {
                "status": "validation_failed",
                "request_id": "req-1",
                "data": {"field": "value"},
                "created_ids": {},
                "warnings": [],
                "errors": [
                    {
                        "code": "VALIDATION_ERROR",
                        "message": "bad input",
                        "entity_type": None,
                        "entity_id": None,
                        "severity": "error",
                    }
                ],
                "lineage": {"account_id": 1},
            },
        )

    def test_api_adapter_does_not_bypass_sqlite_boundary(self) -> None:
        api_dir = Path(__file__).resolve().parents[1] / "src" / "pgc_trading" / "api"
        source = "\n".join(path.read_text() for path in api_dir.glob("*.py"))

        self.assertNotIn("import sqlite3", source)
        self.assertNotIn(".connect(", source)


if __name__ == "__main__":
    unittest.main()
