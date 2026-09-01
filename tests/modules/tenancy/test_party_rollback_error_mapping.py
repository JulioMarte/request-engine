"""Rollback route typed-error mapping and capability-gate rejections.

`parties.rollback_identity` maps the typed revision errors to their HTTP
statuses (revision not found -> 404, target ahead of the cursor -> 422) and
never reaches the handler without the capability grant. Recording doubles;
no database is involved.
"""

from uuid import uuid4

import pytest
from _party_revision_route_support import actor, app, party
from httpx import ASGITransport, AsyncClient

from request_engine.modules.tenancy.application.commands.rollback_party_identity import (
    RollbackPartyIdentityCommand,
)
from request_engine.modules.tenancy.application.errors import (
    PartyRevisionNotFound,
    PartyRevisionTargetInvalid,
)
from request_engine.modules.tenancy.application.queries.party_revision_history import (
    PartyRevisionHistoryQuery,
)
from request_engine.modules.tenancy.contracts.party_registry import (
    PartyRevision,
    RegisteredParty,
)


class _FailingRollbacks:
    def __init__(self, outcome: RegisteredParty | Exception) -> None:
        self._outcome = outcome
        self.count = 0

    async def rollback_party_identity(
        self, command: RollbackPartyIdentityCommand
    ) -> RegisteredParty:
        del command
        self.count += 1
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


async def _rollback(rollbacks: _FailingRollbacks, target_revision: int, *, granted: bool = True):
    capabilities = ("parties.rollback_identity",) if granted else ()
    test_app = app(
        actor(*capabilities),
        _NeverReadsHistory(),
        rollbacks,
    )
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        return await client.post(
            f"/v1/parties/{uuid4()}/rollback",
            json={"target_revision": target_revision},
            headers={"Idempotency-Key": "error-mapping"},
        )


class _NeverReadsHistory:
    async def revision_history(self, query: PartyRevisionHistoryQuery) -> tuple[PartyRevision, ...]:
        del query
        raise AssertionError("history reader must not be reached by rollback tests")


@pytest.mark.asyncio
async def test_revision_not_found_maps_to_404() -> None:
    rollbacks = _FailingRollbacks(PartyRevisionNotFound(uuid4(), 3))
    response = await _rollback(rollbacks, 3)
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "party_revision_not_found"


@pytest.mark.asyncio
async def test_target_ahead_of_cursor_maps_to_422() -> None:
    rollbacks = _FailingRollbacks(PartyRevisionTargetInvalid(uuid4(), 9, 4))
    response = await _rollback(rollbacks, 9)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "party_revision_target_invalid"
    assert response.json()["error"]["details"]["current_revision"] == 4


@pytest.mark.asyncio
async def test_rollback_never_reaches_handler_without_grant() -> None:
    rollbacks = _FailingRollbacks(party())
    response = await _rollback(rollbacks, 1, granted=False)
    assert response.status_code == 403, response.text
    assert rollbacks.count == 0
