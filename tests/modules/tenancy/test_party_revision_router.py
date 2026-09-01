"""Revision history and rollback route shape and command mapping."""

from uuid import uuid4

import pytest
from _party_revision_route_support import actor, app, party, revision
from httpx import ASGITransport, AsyncClient

from request_engine.modules.tenancy.application.commands.rollback_party_identity import (
    RollbackPartyIdentityCommand,
)
from request_engine.modules.tenancy.application.queries.party_revision_history import (
    PartyRevisionHistoryQuery,
)
from request_engine.modules.tenancy.contracts.party_registry import PartyRevision, RegisteredParty


class _RecordingHistoryReader:
    def __init__(self, revisions: tuple[PartyRevision, ...]) -> None:
        self._revisions = revisions
        self.queries: list[PartyRevisionHistoryQuery] = []

    async def revision_history(self, query: PartyRevisionHistoryQuery) -> tuple[PartyRevision, ...]:
        self.queries.append(query)
        return self._revisions


class _RecordingRollbacks:
    def __init__(self, party_view: RegisteredParty) -> None:
        self._party_view = party_view
        self.commands: list[RollbackPartyIdentityCommand] = []

    async def rollback_party_identity(
        self, command: RollbackPartyIdentityCommand
    ) -> RegisteredParty:
        self.commands.append(command)
        return self._party_view


@pytest.mark.asyncio
async def test_history_route_maps_query_and_returns_revision_views() -> None:
    actor_context = actor("parties.read_revisions")
    reader = _RecordingHistoryReader((revision(1), revision(2)))
    test_app = app(actor_context, reader, _RecordingRollbacks(party()))
    party_id = uuid4()

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        response = await client.get(f"/v1/parties/{party_id}/revisions")

    assert response.status_code == 200, response.text
    assert reader.queries[0].party_id == party_id
    assert reader.queries[0].organization_id == actor_context.organization_id
    revisions = response.json()
    assert [item["revision"] for item in revisions] == [1, 2]
    assert revisions[0]["change_kind"] == "renamed"
    assert revisions[0]["source_kind"] == "operator"
    assert revisions[0]["platform"] == "reception_web"
    assert revisions[0]["snapshot"] == {"display_name": "Jose Perez", "active": True}


@pytest.mark.asyncio
async def test_rollback_route_maps_body_into_command() -> None:
    actor_context = actor("parties.rollback_identity")
    party_view = party()
    rollbacks = _RecordingRollbacks(party_view)
    test_app = app(actor_context, _RecordingHistoryReader(()), rollbacks)
    party_id = uuid4()

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        response = await client.post(
            f"/v1/parties/{party_id}/rollback",
            json={"target_revision": 1},
            headers={"Idempotency-Key": "rollback-1"},
        )

    assert response.status_code == 200, response.text
    assert rollbacks.commands[0].party_id == party_id
    assert rollbacks.commands[0].target_revision == 1
    assert rollbacks.commands[0].organization_id == actor_context.organization_id
    assert response.json()["party_id"] == str(party_view.party_id)
