import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from request_engine.modules.live_capacity.contracts.projection import ProjectionState
from request_engine.modules.live_capacity.contracts.recovery import (
    RecoveryCapacityAssessment,
    RecoveryCapacityCheckpoint,
    RecoveryCommitmentFact,
)
from request_engine.modules.operational_copilot.application.copilot import OperationalCopilot
from request_engine.modules.operational_copilot.contracts import (
    AtRiskReservationsQuery,
    CopilotContext,
)
from request_engine.modules.operational_copilot.errors import UnsupportedCopilotIntent

ORG = UUID("11111111-1111-1111-1111-111111111111")
PRINCIPAL = UUID("22222222-2222-2222-2222-222222222222")
QUEUE = UUID("33333333-3333-3333-3333-333333333333")
CTX = CopilotContext(ORG, PRINCIPAL, "copilot:inspect:1")


class StubAtRiskReader:
    def __init__(self) -> None:
        self.queries: list[AtRiskReservationsQuery] = []
        self.assessment = RecoveryCapacityAssessment(
            service_queue_id=QUEUE,
            resource_id=uuid4(),
            location_id=uuid4(),
            observed_at=datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
            horizon_end=datetime(2026, 8, 30, 20, 0, tzinfo=UTC),
            projection_state=ProjectionState.KNOWN,
            projection_reasons=(),
            executable_capacity_seconds=3600,
            committed_capacity_seconds=5400,
            scheduled_shortfall_seconds=1800,
            live_shortfall_seconds=1800,
            shortfall_seconds=1800,
            source_fingerprint="stub-source-fingerprint",
            source_snapshot={},
            checkpoint=RecoveryCapacityCheckpoint(1, 1, 1, 1, ()),
            affected_commitments=(
                RecoveryCommitmentFact(
                    reservation_id=uuid4(),
                    offering_version_id=uuid4(),
                    subject_party_id=uuid4(),
                    reservation_revision=2,
                    planned_starts_at=datetime(2026, 8, 30, 14, 0, tzinfo=UTC),
                    planned_ends_at=datetime(2026, 8, 30, 14, 30, tzinfo=UTC),
                    planned_duration_seconds=1800,
                ),
            ),
        )

    async def read(self, query: AtRiskReservationsQuery) -> RecoveryCapacityAssessment:
        self.queries.append(query)
        return self.assessment


def test_at_risk_intent_lowers_to_tenant_scoped_query() -> None:
    copilot = OperationalCopilot(StubAtRiskReader())
    operation = _run_interpret(copilot, f"show reservations at risk for queue {QUEUE}")
    assert operation == AtRiskReservationsQuery(ORG, QUEUE)


@pytest.mark.asyncio
async def test_inspection_reads_through_port_with_trusted_scope() -> None:
    reader = StubAtRiskReader()
    copilot = OperationalCopilot(reader)
    assessment = await copilot.inspect_at_risk(CTX, f"show reservations at risk for queue {QUEUE}")
    assert reader.queries == [AtRiskReservationsQuery(ORG, QUEUE)]
    assert assessment.shortfall_seconds == 1800
    assert len(assessment.affected_commitments) == 1


def test_inspection_surface_refuses_mutation_text() -> None:
    copilot = OperationalCopilot(StubAtRiskReader())
    with pytest.raises(UnsupportedCopilotIntent):
        _run_interpret(copilot, "drop table reservations")


def test_names_are_never_resolved_to_queues() -> None:
    copilot = OperationalCopilot(StubAtRiskReader())
    with pytest.raises(UnsupportedCopilotIntent):
        _run_interpret(copilot, "show reservations at risk for queue Dr. A")


def _run_interpret(copilot: OperationalCopilot, text: str):
    return asyncio.run(copilot.interpret(CTX, text))
