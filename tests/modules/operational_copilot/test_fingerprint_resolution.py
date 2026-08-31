import asyncio
from datetime import UTC, datetime
from uuid import UUID

import pytest

from request_engine.modules.operational_copilot.application.fingerprint_resolution import (
    resolve_execute_fingerprints,
)
from request_engine.modules.operational_copilot.contracts import (
    CopilotContext,
    ExecuteRecoveryIntent,
)
from request_engine.modules.operational_copilot.errors import CopilotResolutionFailed
from request_engine.modules.operational_copilot.parser import parse_copilot_intent
from request_engine.modules.operational_recovery.contracts.models import (
    RecoverySourceCheckpoint,
    RescheduleProposal,
)

ORG = UUID("11111111-1111-1111-1111-111111111111")
PROPOSAL = UUID("44444444-4444-4444-4444-444444444444")
RESERVATION = UUID("55555555-5555-5555-5555-555555555555")
CTX = CopilotContext(ORG, UUID("22222222-2222-2222-2222-222222222222"), "copilot:execute:1")


class StubProposalReader:
    def __init__(self, fingerprints: tuple[str, str] | Exception) -> None:
        self.result = fingerprints
        self.reads = 0

    async def get_proposal(self, *, organization_id: UUID, proposal_id: UUID) -> RescheduleProposal:
        self.reads += 1
        if isinstance(self.result, Exception):
            raise self.result
        return RescheduleProposal(
            id=proposal_id,
            service_queue_id=UUID("33333333-3333-3333-3333-333333333333"),
            resource_id=UUID("99999999-9999-9999-9999-999999999999"),
            location_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            observed_at=datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
            horizon_end=datetime(2026, 8, 30, 20, 0, tzinfo=UTC),
            source_fingerprint=self.result[0],
            source_snapshot={},
            source_checkpoint=RecoverySourceCheckpoint(1, 1, 1, 4, ()),
            proposal_fingerprint=self.result[1],
            executable_capacity_seconds=1,
            committed_capacity_seconds=2,
            shortfall_seconds=3,
            affected=(),
            created_at=datetime(2026, 8, 30, 11, 0, tzinfo=UTC),
        )


def _unresolved_intent() -> ExecuteRecoveryIntent:
    intent = parse_copilot_intent(
        f"execute recovery proposal {PROPOSAL} for reservation {RESERVATION}"
    )
    assert isinstance(intent, ExecuteRecoveryIntent)
    return intent


def test_execute_without_fingerprints_resolves_through_owner_read() -> None:
    intent = _unresolved_intent()
    assert intent.expected_source_fingerprint is None
    assert intent.expected_proposal_fingerprint is None
    reader = StubProposalReader(("stub-source-fp", "stub-proposal-fp"))
    resolved = asyncio.run(resolve_execute_fingerprints(reader, CTX, intent))
    assert reader.reads == 1
    assert resolved.expected_source_fingerprint == "stub-source-fp"
    assert resolved.expected_proposal_fingerprint == "stub-proposal-fp"


def test_explicit_fingerprints_pass_through_without_resolution() -> None:
    text = (
        f"execute recovery proposal {PROPOSAL} for reservation {RESERVATION} "
        "source given-source proposal given-proposal"
    )
    intent = parse_copilot_intent(text)
    assert isinstance(intent, ExecuteRecoveryIntent)
    assert intent.expected_source_fingerprint == "given-source"
    reader = StubProposalReader(("unwanted", "unwanted"))
    resolved = asyncio.run(resolve_execute_fingerprints(reader, CTX, intent))
    assert resolved.expected_source_fingerprint == "given-source"
    assert resolved.expected_proposal_fingerprint == "given-proposal"
    assert reader.reads == 0


def test_partially_supplied_fingerprints_fail_closed() -> None:
    intent = ExecuteRecoveryIntent(
        proposal_id=PROPOSAL,
        reservation_id=RESERVATION,
        expected_source_fingerprint="only-source",
    )
    reader = StubProposalReader(("unwanted", "unwanted"))
    with pytest.raises(CopilotResolutionFailed):
        asyncio.run(resolve_execute_fingerprints(reader, CTX, intent))
    assert reader.reads == 0


def test_resolution_failure_fails_closed() -> None:
    intent = _unresolved_intent()
    reader = StubProposalReader(RuntimeError("database unavailable"))
    with pytest.raises(CopilotResolutionFailed):
        asyncio.run(resolve_execute_fingerprints(reader, CTX, intent))


def test_replay_resolution_is_deterministic() -> None:
    intent = _unresolved_intent()
    reader = StubProposalReader(("stub-source-fp", "stub-proposal-fp"))
    first = asyncio.run(resolve_execute_fingerprints(reader, CTX, intent))
    second = asyncio.run(resolve_execute_fingerprints(reader, CTX, intent))
    assert first == second
    assert reader.reads == 2
