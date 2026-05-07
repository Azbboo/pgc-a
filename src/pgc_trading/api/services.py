"""Service factory wiring for HTTP route adapters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pgc_trading.reporting.daily_report import ReportingQueryService
from pgc_trading.services.data_quality_service import DataQualityService
from pgc_trading.services.portfolio_planning_service import PortfolioPlanningService
from pgc_trading.services.position_lifecycle_service import PositionLifecycleService


ReportServiceFactory = Callable[[Path], ReportingQueryService]
DataQualityServiceFactory = Callable[[Path], DataQualityService]
PortfolioPlanningServiceFactory = Callable[[Path], PortfolioPlanningService]
PositionLifecycleServiceFactory = Callable[[Path], PositionLifecycleService]


@dataclass(frozen=True)
class ApiServices:
    report_service_factory: ReportServiceFactory = ReportingQueryService
    data_quality_service_factory: DataQualityServiceFactory = DataQualityService
    portfolio_planning_service_factory: PortfolioPlanningServiceFactory = PortfolioPlanningService
    position_lifecycle_service_factory: PositionLifecycleServiceFactory = PositionLifecycleService
