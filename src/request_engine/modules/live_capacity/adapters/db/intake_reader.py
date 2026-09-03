from request_engine.modules.live_capacity.adapters.db.projection_snapshot import (
    capture_projection_snapshot,
)
from request_engine.modules.live_capacity.application.projection_assembly import (
    capacity_intervals,
    existing_work,
    has_open_interruption,
)
from request_engine.modules.live_capacity.application.queries.intake import EvaluateIntakeQuery
from request_engine.modules.live_capacity.application.sources import LiveCapacitySources
from request_engine.modules.live_capacity.contracts.projection import IntakeEvaluation
from request_engine.modules.live_capacity.domain.intake import evaluate_intake
from request_engine.platform.db.read_snapshot import tenant_read_snapshot
from request_engine.platform.db.session import SessionFactory


class PostgresIntakeEvaluationReader:
    def __init__(self, session_factory: SessionFactory, sources: LiveCapacitySources) -> None:
        self._session_factory = session_factory
        self._sources = sources

    async def evaluate(self, query: EvaluateIntakeQuery) -> IntakeEvaluation:
        async with tenant_read_snapshot(self._session_factory, query.organization_id) as session:
            snapshot = await capture_projection_snapshot(
                session,
                sources=self._sources,
                organization_id=query.organization_id,
                service_queue_id=query.service_queue_id,
                additional_workload_ids=(query.workload_classification_id,),
            )
        estimate = snapshot.estimates[query.workload_classification_id]
        return evaluate_intake(
            observed_at=snapshot.observed_at,
            intervals=capacity_intervals(snapshot),
            existing_work=existing_work(snapshot),
            estimate=estimate,
            has_open_interruption=has_open_interruption(snapshot),
            has_open_resource_activity=snapshot.delivery.open_resource_activity is not None,
            has_active_recall_hold=snapshot.queue.has_active_recall_hold,
            has_active_skip=snapshot.queue.has_active_skip,
        )
