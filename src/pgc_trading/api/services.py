"""Service factory wiring for HTTP route adapters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pgc_trading.reporting.daily_report import ReportingQueryService
from pgc_trading.services.data_quality_service import DataQualityService
from pgc_trading.services.daily_close_workflow_service import DailyCloseWorkflowService
from pgc_trading.services.execution_recording_service import ExecutionRecordingService
from pgc_trading.services.market_review_service import MarketReviewService
from pgc_trading.services.open_execution_service import OpenExecutionService
from pgc_trading.services.portfolio_planning_service import PortfolioPlanningService
from pgc_trading.services.position_lifecycle_service import PositionLifecycleService


ReportServiceFactory = Callable[[Path], ReportingQueryService]
DataQualityServiceFactory = Callable[[Path], DataQualityService]
DailyCloseWorkflowServiceFactory = Callable[[Path], DailyCloseWorkflowService]
ExecutionRecordingServiceFactory = Callable[[Path], ExecutionRecordingService]
MarketReviewServiceFactory = Callable[[Path], MarketReviewService]
OpenExecutionServiceFactory = Callable[[Path], OpenExecutionService]
PortfolioPlanningServiceFactory = Callable[[Path], PortfolioPlanningService]
PositionLifecycleServiceFactory = Callable[[Path], PositionLifecycleService]


@dataclass(frozen=True)
class ApiServices:
    report_service_factory: ReportServiceFactory = ReportingQueryService
    data_quality_service_factory: DataQualityServiceFactory = DataQualityService
    daily_close_workflow_service_factory: DailyCloseWorkflowServiceFactory = DailyCloseWorkflowService
    execution_recording_service_factory: ExecutionRecordingServiceFactory = ExecutionRecordingService
    market_review_service_factory: MarketReviewServiceFactory = MarketReviewService
    open_execution_service_factory: OpenExecutionServiceFactory = OpenExecutionService
    portfolio_planning_service_factory: PortfolioPlanningServiceFactory = PortfolioPlanningService
    position_lifecycle_service_factory: PositionLifecycleServiceFactory = PositionLifecycleService
