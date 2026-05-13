"""Service factory wiring for HTTP route adapters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pgc_trading.reporting.daily_report import ReportingQueryService
from pgc_trading.services.data_quality_service import DataQualityService
from pgc_trading.services.daily_close_workflow_service import DailyCloseWorkflowService
from pgc_trading.services.decision_action_log_service import DecisionActionLogService
from pgc_trading.services.execution_recording_service import ExecutionRecordingService
from pgc_trading.services.evidence_coverage_ledger_service import EvidenceCoverageLedgerService
from pgc_trading.services.market_review_service import MarketReviewService
from pgc_trading.services.open_execution_service import OpenExecutionService
from pgc_trading.services.portfolio_planning_service import PortfolioPlanningService
from pgc_trading.services.position_lifecycle_service import PositionLifecycleService
from pgc_trading.services.shadow_observation_service import ShadowObservationService
from pgc_trading.services.shadow_strategy_service import ShadowStrategyService
from pgc_trading.services.strategy_evolution_service import StrategyEvolutionService


ReportServiceFactory = Callable[[Path], ReportingQueryService]
DataQualityServiceFactory = Callable[[Path], DataQualityService]
DailyCloseWorkflowServiceFactory = Callable[[Path], DailyCloseWorkflowService]
DecisionActionLogServiceFactory = Callable[[Path], DecisionActionLogService]
ExecutionRecordingServiceFactory = Callable[[Path], ExecutionRecordingService]
EvidenceCoverageLedgerServiceFactory = Callable[[Path], EvidenceCoverageLedgerService]
MarketReviewServiceFactory = Callable[[Path], MarketReviewService]
OpenExecutionServiceFactory = Callable[[Path], OpenExecutionService]
PortfolioPlanningServiceFactory = Callable[[Path], PortfolioPlanningService]
PositionLifecycleServiceFactory = Callable[[Path], PositionLifecycleService]
ShadowObservationServiceFactory = Callable[[Path], ShadowObservationService]
ShadowDecisionMemoServiceFactory = Callable[[Path], ShadowObservationService]
ShadowPromotionReviewServiceFactory = Callable[[Path], ShadowObservationService]
ShadowStrategyServiceFactory = Callable[[Path], ShadowStrategyService]
StrategyEvolutionServiceFactory = Callable[[Path], StrategyEvolutionService]


@dataclass(frozen=True)
class ApiServices:
    report_service_factory: ReportServiceFactory = ReportingQueryService
    data_quality_service_factory: DataQualityServiceFactory = DataQualityService
    daily_close_workflow_service_factory: DailyCloseWorkflowServiceFactory = DailyCloseWorkflowService
    decision_action_log_service_factory: DecisionActionLogServiceFactory = DecisionActionLogService
    execution_recording_service_factory: ExecutionRecordingServiceFactory = ExecutionRecordingService
    evidence_coverage_ledger_service_factory: EvidenceCoverageLedgerServiceFactory = EvidenceCoverageLedgerService
    market_review_service_factory: MarketReviewServiceFactory = MarketReviewService
    open_execution_service_factory: OpenExecutionServiceFactory = OpenExecutionService
    portfolio_planning_service_factory: PortfolioPlanningServiceFactory = PortfolioPlanningService
    position_lifecycle_service_factory: PositionLifecycleServiceFactory = PositionLifecycleService
    shadow_observation_service_factory: ShadowObservationServiceFactory = ShadowObservationService
    shadow_decision_memo_service_factory: ShadowDecisionMemoServiceFactory = ShadowObservationService
    shadow_promotion_review_service_factory: ShadowPromotionReviewServiceFactory = ShadowObservationService
    shadow_strategy_service_factory: ShadowStrategyServiceFactory = ShadowStrategyService
    strategy_evolution_service_factory: StrategyEvolutionServiceFactory = StrategyEvolutionService
