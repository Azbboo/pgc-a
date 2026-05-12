"""Build auditable provider-file packs for reviewed market and Agent evidence."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from pgc_trading.config import Paths
from pgc_trading.services.agent_external_data_service import (
    AgentExternalDataService,
    BackfillAgentExternalDataRequest,
)
from pgc_trading.services.common import RequestContext, ServiceError, ServiceResult
from pgc_trading.services.market_external_data_service import (
    BackfillMarketExternalDataRequest,
    MarketExternalDataService,
)


EVIDENCE_PROVIDER_PACK_CONTRACT = "evidence_provider_pack_v1"


@dataclass(frozen=True)
class BuildEvidenceProviderPackRequest:
    market_source_files: list[Path] = field(default_factory=list)
    agent_source_files: list[Path] = field(default_factory=list)
    output_dir: Path | None = None
    encoding: str = "utf-8"


@dataclass(frozen=True)
class EvidenceProviderPackResult:
    pack_contract: str = EVIDENCE_PROVIDER_PACK_CONTRACT
    generated_at: str = ""
    db_path: str = ""
    output_dir: str | None = None
    apply: bool = False
    source_file_count: int = 0
    date_count: int = 0
    ready_date_count: int = 0
    blocking_date_count: int = 0
    groups: list[dict[str, Any]] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)
    manifest_path: str | None = None
    copied_files: list[str] = field(default_factory=list)


class EvidenceProviderPackService:
    """Prepare cached provider-file packs without fetching live data."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or Paths().db_path

    def build_provider_pack(
        self,
        request: BuildEvidenceProviderPackRequest,
        ctx: RequestContext,
    ) -> ServiceResult[EvidenceProviderPackResult]:
        market_files = [Path(path) for path in request.market_source_files]
        agent_files = [Path(path) for path in request.agent_source_files]
        if not market_files and not agent_files:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=self._empty_result(request, ctx),
                errors=[ServiceError("VALIDATION_ERROR", "at least one market_source_file or agent_source_file is required.")],
            )

        group_results: list[dict[str, Any]] = []
        errors: list[ServiceError] = []

        if market_files:
            market_result = MarketExternalDataService(self.db_path).backfill_external_data(
                BackfillMarketExternalDataRequest(source_files=market_files, encoding=request.encoding),
                RequestContext(
                    request_id=ctx.request_id,
                    idempotency_key=ctx.idempotency_key,
                    dry_run=True,
                    operator=ctx.operator,
                    source=ctx.source,
                ),
            )
            group_results.append(
                _market_group_manifest(
                    market_result.data,
                    market_files,
                    apply=not ctx.dry_run,
                    output_dir=request.output_dir,
                )
            )
            if not market_result.ok:
                errors.extend(market_result.errors)

        if agent_files:
            agent_result = AgentExternalDataService(self.db_path).backfill_external_data(
                BackfillAgentExternalDataRequest(source_files=agent_files, encoding=request.encoding),
                RequestContext(
                    request_id=ctx.request_id,
                    idempotency_key=ctx.idempotency_key,
                    dry_run=True,
                    operator=ctx.operator,
                    source=ctx.source,
                ),
            )
            group_results.append(
                _agent_group_manifest(
                    agent_result.data,
                    agent_files,
                    apply=not ctx.dry_run,
                    output_dir=request.output_dir,
                )
            )
            if not agent_result.ok:
                errors.extend(agent_result.errors)

        output_dir = _pack_output_dir(request.output_dir)
        manifest = _build_pack_manifest(
            self.db_path,
            output_dir,
            ctx,
            group_results,
            apply=not ctx.dry_run,
        )

        if ctx.dry_run or errors:
            return ServiceResult(
                status="validation_failed" if errors else "success",
                request_id=ctx.request_id,
                data=EvidenceProviderPackResult(
                    generated_at=manifest["generated_at"],
                    db_path=str(self.db_path),
                    output_dir=str(output_dir) if output_dir is not None else None,
                    apply=not ctx.dry_run,
                    source_file_count=manifest["source_file_count"],
                    date_count=manifest["date_count"],
                    ready_date_count=manifest["ready_date_count"],
                    blocking_date_count=manifest["blocking_date_count"],
                    groups=group_results,
                    manifest=manifest,
                ),
                errors=errors,
            )

        if output_dir is None:
            return ServiceResult(
                status="validation_failed",
                request_id=ctx.request_id,
                data=self._empty_result(request, ctx, groups=group_results, manifest=manifest),
                errors=[ServiceError("VALIDATION_ERROR", "output_dir is required when apply is enabled.")],
            )

        output_dir.mkdir(parents=True, exist_ok=True)
        copied_files: list[str] = []
        for group in group_results:
            for date_result in group.get("date_results", []):
                for artifact in date_result.get("source_files", []):
                    destination = Path(artifact["output_file"])
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(Path(artifact["source_file"]), destination)
                    copied_files.append(str(destination))

        manifest_path = output_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        return ServiceResult(
            status="success",
            request_id=ctx.request_id,
            data=EvidenceProviderPackResult(
                generated_at=manifest["generated_at"],
                db_path=str(self.db_path),
                output_dir=str(output_dir),
                apply=True,
                source_file_count=manifest["source_file_count"],
                date_count=manifest["date_count"],
                ready_date_count=manifest["ready_date_count"],
                blocking_date_count=manifest["blocking_date_count"],
                groups=group_results,
                manifest=manifest,
                manifest_path=str(manifest_path),
                copied_files=copied_files,
            ),
            lineage={"output_dir": str(output_dir), "manifest_path": str(manifest_path)},
        )

    def _empty_result(
        self,
        request: BuildEvidenceProviderPackRequest,
        ctx: RequestContext,
        *,
        groups: list[dict[str, Any]] | None = None,
        manifest: dict[str, Any] | None = None,
    ) -> EvidenceProviderPackResult:
        output_dir = str(_pack_output_dir(request.output_dir)) if request.output_dir is not None else None
        built_manifest = manifest or _build_pack_manifest(
            self.db_path,
            _pack_output_dir(request.output_dir),
            ctx,
            groups or [],
            apply=not ctx.dry_run,
        )
        return EvidenceProviderPackResult(
            generated_at=built_manifest["generated_at"],
            db_path=str(self.db_path),
            output_dir=output_dir,
            apply=not ctx.dry_run,
            source_file_count=built_manifest["source_file_count"],
            date_count=built_manifest["date_count"],
            ready_date_count=built_manifest["ready_date_count"],
            blocking_date_count=built_manifest["blocking_date_count"],
            groups=groups or [],
            manifest=built_manifest,
        )


def _pack_output_dir(output_dir: Path | None) -> Path | None:
    if output_dir is None:
        return None
    return Path(output_dir).expanduser()


def _build_pack_manifest(
    db_path: Path,
    output_dir: Path | None,
    ctx: RequestContext,
    groups: Sequence[dict[str, Any]],
    *,
    apply: bool,
) -> dict[str, Any]:
    source_file_count = sum(group.get("source_file_count", 0) for group in groups)
    date_count = sum(group.get("date_count", 0) for group in groups)
    ready_date_count = sum(len(group.get("ready_dates", [])) for group in groups)
    blocking_date_count = sum(len(group.get("blocking_dates", [])) for group in groups)
    return {
        "pack_contract": EVIDENCE_PROVIDER_PACK_CONTRACT,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "db_path": str(db_path),
        "output_dir": str(output_dir) if output_dir is not None else None,
        "apply": apply,
        "request": {
            "request_id": ctx.request_id,
            "operator": ctx.operator,
            "dry_run": ctx.dry_run,
            "source": ctx.source,
        },
        "source_file_count": source_file_count,
        "date_count": date_count,
        "ready_date_count": ready_date_count,
        "blocking_date_count": blocking_date_count,
        "provider_file_contracts": [
            group["provider_file_contract"]
            for group in groups
            if group.get("provider_file_contract")
        ],
        "groups": list(groups),
    }


def _market_group_manifest(
    result: object | None,
    source_files: Sequence[Path],
    *,
    apply: bool,
    output_dir: Path | None,
) -> dict[str, Any]:
    if result is None:
        return {
            "kind": "market_external",
            "provider_file_contract": "market_external_v1",
            "source_file_count": len(source_files),
            "date_count": 0,
            "ready_dates": [],
            "blocking_dates": [],
            "coverage_qa": {},
            "date_results": [],
        }

    coverage_qa = dict(getattr(result, "coverage_qa", {}))
    date_results = []
    for item in getattr(result, "date_results", []):
        source_file_entries = _source_file_entries(
            "market_external",
            item.as_of_date,
            getattr(item, "source_files", []),
            source_files,
            apply=apply,
            output_dir=output_dir,
        )
        date_results.append(
            {
                "as_of_date": item.as_of_date,
                "source_files": source_file_entries,
                "row_count": getattr(item, "row_count", 0),
                "valid_count": getattr(item, "valid_count", 0),
                "invalid_count": getattr(item, "invalid_count", 0),
                "would_insert_count": getattr(item, "would_insert_count", 0),
                "inserted_count": getattr(item, "inserted_count", 0),
                "duplicate_count": getattr(item, "duplicate_count", 0),
                "coverage_summary": getattr(item, "coverage_summary", {}),
                "coverage_details": getattr(item, "coverage_details", {}),
                "unavailable_sources": getattr(item, "unavailable_sources", []),
            }
        )

    return {
        "kind": "market_external",
        "provider_file_contract": getattr(result, "provider_file_contract", "market_external_v1"),
        "source_file_count": len(source_files),
        "date_count": getattr(result, "date_count", len(date_results)),
        "ready_dates": coverage_qa.get("ready_dates", []),
        "blocking_dates": coverage_qa.get("blocking_dates", []),
        "coverage_qa": coverage_qa,
        "date_results": date_results,
    }


def _agent_group_manifest(
    result: object | None,
    source_files: Sequence[Path],
    *,
    apply: bool,
    output_dir: Path | None,
) -> dict[str, Any]:
    if result is None:
        return {
            "kind": "agent_external",
            "provider_file_contract": "agent_external_v1",
            "source_file_count": len(source_files),
            "date_count": 0,
            "ready_dates": [],
            "blocking_dates": [],
            "coverage_qa": {},
            "date_results": [],
        }

    coverage_qa = dict(getattr(result, "coverage_qa", {}))
    date_results = []
    for item in getattr(result, "date_results", []):
        source_file_entries = _source_file_entries(
            "agent_external",
            item.as_of_date,
            getattr(item, "source_files", []),
            source_files,
            apply=apply,
            output_dir=output_dir,
        )
        date_results.append(
            {
                "as_of_date": item.as_of_date,
                "source_files": source_file_entries,
                "row_count": getattr(item, "row_count", 0),
                "valid_count": getattr(item, "valid_count", 0),
                "invalid_count": getattr(item, "invalid_count", 0),
                "would_insert_count": getattr(item, "would_insert_count", 0),
                "inserted_count": getattr(item, "inserted_count", 0),
                "updated_count": getattr(item, "updated_count", 0),
                "duplicate_count": getattr(item, "duplicate_count", 0),
                "coverage_summary": getattr(item, "coverage_summary", {}),
                "unavailable_sources": getattr(item, "unavailable_sources", []),
            }
        )

    return {
        "kind": "agent_external",
        "provider_file_contract": getattr(result, "provider_file_contract", "agent_external_v1"),
        "source_file_count": len(source_files),
        "date_count": getattr(result, "date_count", len(date_results)),
        "ready_dates": coverage_qa.get("ready_dates", []),
        "blocking_dates": coverage_qa.get("blocking_dates", []),
        "coverage_qa": coverage_qa,
        "date_results": date_results,
    }


def _source_file_entries(
    group_kind: str,
    as_of_date: str,
    source_file_names: Sequence[str],
    source_files: Sequence[Path],
    *,
    apply: bool,
    output_dir: Path | None,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    source_map = {str(Path(path)): Path(path) for path in source_files}
    for index, source_name in enumerate(source_file_names, start=1):
        source_path = source_map.get(str(Path(source_name)), Path(source_name))
        sha256 = _sha256_file(source_path)
        output_file = None
        if output_dir is not None:
            output_file = output_dir / group_kind / f"{as_of_date}__{index:02d}__{source_path.name}"
        entries.append(
            {
                "source_file": str(source_path),
                "source_file_sha256": sha256,
                "output_file": str(output_file) if output_file is not None else None,
                "written": apply and output_file is not None,
            }
        )
    return entries


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()
