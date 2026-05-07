# ADR: DEV9 HTTP API Technology

Date: 2026-05-07

Status: accepted for DEV9A

## Context

The PGC system already has a CLI and application service layer. DEV9 adds an HTTP API for the future dashboard, but the API must remain a thin adapter over those services. The repository previously had no dependency metadata and the current local Python environment does not include a web framework.

The API needs:

- Typed request and response contracts for dashboard integration.
- OpenAPI documentation without hand-maintained schema files.
- Testable route adapters that do not import `sqlite3` or bypass services.
- A write gate so P0 mutation endpoints remain disabled unless explicitly enabled.

## Decision

Use FastAPI for the DEV9 HTTP API.

Dependency metadata now lives in `pyproject.toml`. The base package has no runtime dependencies, and API runtime dependencies are opt-in through the `api` extra:

```bash
python3 -m pip install -e '.[api]'
```

The initial DEV9A skeleton exposes an app factory at `pgc_trading.api.create_app`. The package remains importable without FastAPI installed; calling `create_app()` without the `api` extra raises a clear `ApiDependencyError` with the install command.

## Consequences

- FastAPI will provide OpenAPI and validation support for DEV9B/DEV9C without custom schema generation.
- Uvicorn is the local ASGI server for manual smoke testing.
- CI and local verification can keep running the existing non-API suite without installing API dependencies.
- API tests that require FastAPI should remain conditional or run in an environment that installs `.[api]`.

## Guardrails

- API routes must call application services instead of reading or writing SQLite directly.
- API write routes must create `RequestContext(source="api")`.
- API writes remain disabled unless `PGC_API_ENABLE_WRITES=1` is set.
- Responses and logs must not expose tokens, database passwords, broker credentials, or raw environment dumps.
