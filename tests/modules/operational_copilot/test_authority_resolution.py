import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from request_engine.modules.operational_copilot.application.authority import (
    resolve_trusted_authority_party,
)
from request_engine.modules.operational_copilot.contracts import (
    CopilotContext,
    ExtendRecoveryDayIntent,
    PublishDiscoverySupplyIntent,
    SetRecoveryIntakeIntent,
)
from request_engine.modules.operational_copilot.errors import CopilotPolicyRejected

ORG = UUID("11111111-1111-1111-1111-111111111111")
PRINCIPAL = UUID("22222222-2222-2222-2222-222222222222")
INCIDENT = UUID("00000000-0000-4000-8000-000000000001")
ASSIGNMENT = UUID("00000000-0000-4000-8000-000000000002")
CTX = CopilotContext(ORG, PRINCIPAL, "key-1")


class StubAuthorityReader:
    def __init__(self, party: UUID | None) -> None:
        self.party = party
        self.calls = 0

    async def resolve_operational_party(
        self, *, organization_id: UUID, principal_id: UUID, scope_keys: frozenset[str]
    ) -> UUID | None:
        self.calls += 1
        del organization_id, principal_id, scope_keys
        return self.party


def _extend_intent() -> ExtendRecoveryDayIntent:
    return ExtendRecoveryDayIntent(
        incident_id=INCIDENT,
        assignment_id=UUID("00000000-0000-4000-8000-000000000003"),
        start_at=_at(17, 0),
        end_at=_at(19, 0),
        expected_source_revision=1,
        expected_location_operational_revision=1,
        expected_resource_availability_revision=1,
        reason="probe",
    )


def test_authority_resolved_from_reader_for_authority_intents() -> None:
    party = uuid4()
    for intent in (
        _extend_intent(),
        PublishDiscoverySupplyIntent(
            UUID("00000000-0000-4000-8000-000000000004"),
            UUID("00000000-0000-4000-8000-000000000005"),
            _at(8, 0),
        ),
    ):
        reader = StubAuthorityReader(party)
        context = asyncio.run(resolve_trusted_authority_party(reader, CTX, intent))
        assert reader.calls == 1
        assert context.authority_party_id == party


def test_absent_authority_refuses() -> None:
    reader = StubAuthorityReader(None)
    with pytest.raises(CopilotPolicyRejected):
        asyncio.run(resolve_trusted_authority_party(reader, CTX, _extend_intent()))


def test_non_authority_intent_skips_resolution() -> None:
    reader = StubAuthorityReader(None)
    context = asyncio.run(
        resolve_trusted_authority_party(reader, CTX, SetRecoveryIntakeIntent(INCIDENT, False, 1, 1))
    )
    assert reader.calls == 0
    assert context.authority_party_id is None


def test_already_resolved_context_is_preserved() -> None:
    reader = StubAuthorityReader(None)
    context = CopilotContext(ORG, PRINCIPAL, "key-1", authority_party_id=UUID(int=7))
    resolved = asyncio.run(resolve_trusted_authority_party(reader, context, _extend_intent()))
    assert reader.calls == 0
    assert resolved.authority_party_id == UUID(int=7)


def _at(hour: int, minute: int):
    return datetime(2026, 9, 1, hour, minute, tzinfo=UTC)
