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
MARKET_PROVIDER_PACK_REQUIRED_SECTIONS = ("market", "sector", "stock", "news", "sentiment")
AGENT_PROVIDER_PACK_REQUIRED_SECTIONS = ("fundamental", "announcement", "news", "sentiment")
PACK_QA_CLOSED_STATES = {"available", "unavailable"}
PACK_QA_REVIEW_STATES = {"partial", "stale", "duplicate", "invalid", "source-hash-mismatch"}


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
    qa_summary: dict[str, Any] = field(default_factory=dict)
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
            errors=errors,
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
                    qa_summary=manifest["qa_summary"],
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
                qa_summary=manifest["qa_summary"],
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
            qa_summary=built_manifest["qa_summary"],
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
    errors: Sequence[ServiceError] = (),
) -> dict[str, Any]:
    source_file_count = sum(group.get("source_file_count", 0) for group in groups)
    date_count = sum(group.get("date_count", 0) for group in groups)
    ready_date_count = sum(len(group.get("ready_dates", [])) for group in groups)
    blocking_date_count = sum(len(group.get("blocking_dates", [])) for group in groups)
    qa_summary = _build_pack_qa_summary(groups, errors)
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
        "qa_summary": qa_summary,
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
            "source_files": [str(path) for path in source_files],
            "source_file_count": len(source_files),
            "date_count": 0,
            "ready_dates": [],
            "blocking_dates": [],
            "coverage_qa": {},
            "date_results": [],
            "invalid_records": [],
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
        "source_files": [str(path) for path in source_files],
        "source_file_count": len(source_files),
        "date_count": getattr(result, "date_count", len(date_results)),
        "ready_dates": coverage_qa.get("ready_dates", []),
        "blocking_dates": coverage_qa.get("blocking_dates", []),
        "coverage_qa": coverage_qa,
        "date_results": date_results,
        "invalid_records": _invalid_record_entries(getattr(result, "invalid_records", [])),
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
            "source_files": [str(path) for path in source_files],
            "source_file_count": len(source_files),
            "date_count": 0,
            "ready_dates": [],
            "blocking_dates": [],
            "coverage_qa": {},
            "date_results": [],
            "invalid_records": [],
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
        "source_files": [str(path) for path in source_files],
        "source_file_count": len(source_files),
        "date_count": getattr(result, "date_count", len(date_results)),
        "ready_dates": coverage_qa.get("ready_dates", []),
        "blocking_dates": coverage_qa.get("blocking_dates", []),
        "coverage_qa": coverage_qa,
        "date_results": date_results,
        "invalid_records": _invalid_record_entries(getattr(result, "invalid_records", [])),
    }


def _build_pack_qa_summary(
    groups: Sequence[dict[str, Any]],
    errors: Sequence[ServiceError],
) -> dict[str, Any]:
    closed_gaps: list[dict[str, Any]] = []
    remaining_gaps: list[dict[str, Any]] = []
    provider_files_needing_review: list[dict[str, Any]] = []
    provider_files_needed: list[dict[str, Any]] = []
    ready_dates: set[str] = set()
    blocking_dates: set[str] = set()

    for group in groups:
        kind = str(group.get("kind") or "unknown")
        ready_dates.update(_string_values(group.get("ready_dates")))
        blocking_dates.update(_string_values(group.get("blocking_dates")))
        source_files = _string_values(group.get("source_files"))

        for invalid_record in _mapping_values(group.get("invalid_records")):
            gap = {
                "kind": kind,
                "as_of_date": str(invalid_record.get("as_of_date") or "unknown"),
                "section": str(invalid_record.get("field") or "record"),
                "state": "invalid",
                "reason": str(invalid_record.get("code") or "VALIDATION_ERROR"),
                "message": str(invalid_record.get("message") or ""),
            }
            _append_unique(remaining_gaps, gap)
            for source_file in source_files:
                _append_unique(
                    provider_files_needing_review,
                    {
                        "kind": kind,
                        "as_of_date": gap["as_of_date"],
                        "source_file": source_file,
                        "state": "invalid",
                        "reason": gap["reason"],
                    },
                )

        for date_result in _mapping_values(group.get("date_results")):
            as_of_date = str(date_result.get("as_of_date") or "unknown")
            result_source_files = [
                str(entry.get("source_file"))
                for entry in _mapping_values(date_result.get("source_files"))
                if entry.get("source_file")
            ] or source_files
            coverage_summary = _mapping(date_result.get("coverage_summary"))
            coverage_details = _mapping(date_result.get("coverage_details"))
            required_sections = (
                MARKET_PROVIDER_PACK_REQUIRED_SECTIONS
                if kind == "market_external"
                else AGENT_PROVIDER_PACK_REQUIRED_SECTIONS
            )

            for section in required_sections:
                state = _coverage_section_state(kind, coverage_summary, section)
                gap = {"kind": kind, "as_of_date": as_of_date, "section": section, "state": state}
                if state in PACK_QA_CLOSED_STATES:
                    _append_unique(closed_gaps, gap)
                else:
                    _append_unique(remaining_gaps, gap)
                    if state == "missing":
                        _append_unique(
                            provider_files_needed,
                            {
                                "kind": kind,
                                "as_of_date": as_of_date,
                                "section": section,
                                "reason": "missing_provider_section",
                            },
                        )
                    elif state in PACK_QA_REVIEW_STATES:
                        _append_review_files(
                            provider_files_needing_review,
                            kind=kind,
                            as_of_date=as_of_date,
                            source_files=result_source_files,
                            state=state,
                            reason=f"{section}_{state}",
                        )

            _append_freshness_gaps(
                kind,
                as_of_date,
                coverage_summary,
                remaining_gaps,
                provider_files_needing_review,
                result_source_files,
            )
            duplicate_count = _int_value(
                date_result.get("duplicate_count")
                or coverage_details.get("duplicate_count")
                or coverage_summary.get("duplicate_count")
            )
            if duplicate_count:
                _append_unique(
                    remaining_gaps,
                    {
                        "kind": kind,
                        "as_of_date": as_of_date,
                        "section": "duplicates",
                        "state": "duplicate",
                        "count": duplicate_count,
                    },
                )
                _append_review_files(
                    provider_files_needing_review,
                    kind=kind,
                    as_of_date=as_of_date,
                    source_files=result_source_files,
                    state="duplicate",
                    reason="duplicate_source_hash",
                )
            invalid_count = _int_value(date_result.get("invalid_count", 0))
            if invalid_count:
                _append_unique(
                    remaining_gaps,
                    {
                        "kind": kind,
                        "as_of_date": as_of_date,
                        "section": "invalid_records",
                        "state": "invalid",
                        "count": invalid_count,
                    },
                )
                _append_review_files(
                    provider_files_needing_review,
                    kind=kind,
                    as_of_date=as_of_date,
                    source_files=result_source_files,
                    state="invalid",
                    reason="invalid_records",
                )

            for unavailable_source in _mapping_values(date_result.get("unavailable_sources")):
                section = _unavailable_section(kind, unavailable_source)
                _append_unique(
                    closed_gaps,
                    {
                        "kind": kind,
                        "as_of_date": as_of_date,
                        "section": section,
                        "state": "unavailable",
                        "provider": str(unavailable_source.get("provider") or "unknown"),
                        "reason": str(unavailable_source.get("reason") or "provider_unavailable"),
                    },
                )

    if errors:
        for group in groups:
            if not _mapping_values(group.get("invalid_records")) and _mapping_values(group.get("date_results")):
                continue
            kind = str(group.get("kind") or "unknown")
            for source_file in _string_values(group.get("source_files")):
                _append_unique(
                    provider_files_needing_review,
                    {
                        "kind": kind,
                        "as_of_date": "unknown",
                        "source_file": source_file,
                        "state": "invalid",
                        "reason": "provider_pack_validation_failed",
                    },
                )

    validation_errors = [
        {
            "code": error.code,
            "message": error.message,
            "severity": error.severity,
        }
        for error in errors
    ]
    status = "ready" if not remaining_gaps and not provider_files_needing_review and not validation_errors else "needs_review"
    return {
        "status": status,
        "closed_gap_count": len(closed_gaps),
        "remaining_gap_count": len(remaining_gaps),
        "review_file_count": len(provider_files_needing_review),
        "needed_file_count": len(provider_files_needed),
        "ready_dates": sorted(ready_dates),
        "blocking_dates": sorted(blocking_dates),
        "closed_gaps": closed_gaps,
        "remaining_gaps": remaining_gaps,
        "provider_files_needing_review": provider_files_needing_review,
        "provider_files_needed": provider_files_needed,
        "validation_errors": validation_errors,
        "safety": {
            "reviewed_files_only": True,
            "live_fetches": False,
            "writes_trade_state": False,
            "writes_strategy_state": False,
        },
    }


def _coverage_section_state(kind: str, coverage_summary: Mapping[str, Any], section: str) -> str:
    value = coverage_summary.get(section)
    if kind == "market_external" and section == "news" and value is None:
        value = coverage_summary.get("announcement")
    state = str(value or "missing").strip().lower()
    if state in {"available", "unavailable", "missing", "partial", "stale", "duplicate"}:
        return state
    if state in {"fresh", "none"}:
        return "available"
    return "missing"


def _append_freshness_gaps(
    kind: str,
    as_of_date: str,
    coverage_summary: Mapping[str, Any],
    remaining_gaps: list[dict[str, Any]],
    provider_files_needing_review: list[dict[str, Any]],
    source_files: Sequence[str],
) -> None:
    freshness = coverage_summary.get("freshness")
    if isinstance(freshness, Mapping):
        for scope, raw_state in sorted(freshness.items()):
            state = str(raw_state or "").strip().lower()
            if state in {"stale", "partial"}:
                _append_unique(
                    remaining_gaps,
                    {
                        "kind": kind,
                        "as_of_date": as_of_date,
                        "section": f"freshness:{scope}",
                        "state": state,
                    },
                )
                _append_review_files(
                    provider_files_needing_review,
                    kind=kind,
                    as_of_date=as_of_date,
                    source_files=source_files,
                    state=state,
                    reason=f"freshness_{scope}_{state}",
                )
        return
    state = str(freshness or "").strip().lower()
    if state in {"stale", "partial"}:
        _append_unique(
            remaining_gaps,
            {
                "kind": kind,
                "as_of_date": as_of_date,
                "section": "freshness",
                "state": state,
            },
        )
        _append_review_files(
            provider_files_needing_review,
            kind=kind,
            as_of_date=as_of_date,
            source_files=source_files,
            state=state,
            reason=f"freshness_{state}",
        )


def _append_review_files(
    provider_files_needing_review: list[dict[str, Any]],
    *,
    kind: str,
    as_of_date: str,
    source_files: Sequence[str],
    state: str,
    reason: str,
) -> None:
    for source_file in source_files:
        _append_unique(
            provider_files_needing_review,
            {
                "kind": kind,
                "as_of_date": as_of_date,
                "source_file": source_file,
                "state": state,
                "reason": reason,
            },
        )


def _unavailable_section(kind: str, unavailable_source: Mapping[str, Any]) -> str:
    if kind == "market_external":
        return str(
            unavailable_source.get("item_type")
            or unavailable_source.get("scope_type")
            or unavailable_source.get("scope")
            or "unknown"
        )
    return str(unavailable_source.get("item_type") or unavailable_source.get("category") or "unknown")


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _mapping_values(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _string_values(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None and str(item)]


def _invalid_record_entries(invalid_records: object) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not isinstance(invalid_records, list):
        return entries
    for issue in invalid_records:
        entries.append(
            {
                "index": getattr(issue, "index", None),
                "field": getattr(issue, "field", None),
                "code": getattr(issue, "code", "VALIDATION_ERROR"),
                "message": getattr(issue, "message", ""),
            }
        )
    return entries


def _append_unique(entries: list[dict[str, Any]], entry: dict[str, Any]) -> None:
    if entry not in entries:
        entries.append(entry)


def _int_value(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


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
