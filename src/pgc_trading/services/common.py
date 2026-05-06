"""Common DTOs used by application services."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class RequestContext:
    request_id: str | None = None
    idempotency_key: str | None = None
    dry_run: bool = False
    operator: str | None = None
    source: str = "cli"


@dataclass(frozen=True)
class ServiceWarning:
    code: str
    message: str
    entity_type: str | None = None
    entity_id: int | None = None
    severity: str = "warning"


@dataclass(frozen=True)
class ServiceError:
    code: str
    message: str
    entity_type: str | None = None
    entity_id: int | None = None
    severity: str = "error"


@dataclass(frozen=True)
class ServiceResult(Generic[T]):
    status: str
    request_id: str | None
    data: T | None = None
    created_ids: dict[str, int | list[int]] = field(default_factory=dict)
    warnings: list[ServiceWarning] = field(default_factory=list)
    errors: list[ServiceError] = field(default_factory=list)
    lineage: dict[str, int | str | None] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in {"success", "partial_success", "skipped"}

