"""Idempotent replay must not flow a missing contact point into the view.

When the deserialized replay state no longer contains the addressed contact
point (deactivated between the original command and the replay), the command
raises the typed not-found error instead of returning `None` — which the
transport layer would have turned into a 500. Fake codec inputs replace the
idempotency record; no database is involved.
"""

from typing import cast
from uuid import UUID, uuid4

import pytest

from request_engine.modules.tenancy.adapters.db import (
    party_contact_point_commands,
    party_contact_point_confirmation_commands,
)
from request_engine.modules.tenancy.adapters.db.party_contact_point_commands import (
    PostgresPartyContactPointCommands,
)
from request_engine.modules.tenancy.adapters.db.party_contact_point_confirmation_commands import (
    PostgresPartyContactPointConfirmationCommands,
)
from request_engine.modules.tenancy.application.commands.add_party_contact_point import (
    AddPartyContactPointCommand,
)
from request_engine.modules.tenancy.application.commands.confirm_party_contact_point import (
    ConfirmPartyContactPointCommand,
)
from request_engine.modules.tenancy.application.errors import PartyContactPointNotFound
from request_engine.modules.tenancy.contracts.party_registry import PartySourceKind
from request_engine.platform.db.session import SessionFactory


class _FakeTransaction:
    def __init__(self, session: object) -> None:
        self._session = session

    async def __aenter__(self) -> object:
        return self._session

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


def _replay_party_json() -> dict[str, object]:
    return {
        "party_id": str(uuid4()),
        "organization_id": str(uuid4()),
        "party_kind": "person",
        "display_name": "Paciente Bot",
        "active": True,
        "contact_points": [],
        "documents": [],
    }


def _install_replay(monkeypatch: pytest.MonkeyPatch, target: object) -> UUID:
    party_id = uuid4()
    payload: dict[str, object] = {"party": _replay_party_json()}

    async def fake_acquire(session: object, **kwargs: object) -> tuple[UUID, dict[str, object]]:
        del session, kwargs
        return uuid4(), payload

    def fake_transaction(factory: object, organization_id: UUID) -> _FakeTransaction:
        del factory, organization_id
        return _FakeTransaction(object())

    monkeypatch.setattr(target, "acquire_idempotency", fake_acquire)
    monkeypatch.setattr(target, "tenant_transaction", fake_transaction)
    return party_id


@pytest.mark.asyncio
async def test_add_replay_raises_typed_not_found_when_point_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    party_id = _install_replay(monkeypatch, party_contact_point_commands)
    commands = PostgresPartyContactPointCommands(cast(SessionFactory, object()))
    command = AddPartyContactPointCommand(
        organization_id=uuid4(),
        principal_id=uuid4(),
        party_id=party_id,
        channel="whatsapp",
        value="+18095550110",
        source_kind=PartySourceKind.SUBJECT,
        idempotency_key="replay-add",
    )

    with pytest.raises(PartyContactPointNotFound) as not_found:
        await commands.add_party_contact_point(command)

    assert not_found.value.party_id == party_id
    assert not_found.value.channel == "whatsapp"
    assert not_found.value.normalized_value == "+18095550110"


@pytest.mark.asyncio
async def test_confirm_replay_raises_typed_not_found_when_point_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    party_id = _install_replay(monkeypatch, party_contact_point_confirmation_commands)
    commands = PostgresPartyContactPointConfirmationCommands(cast(SessionFactory, object()))
    contact_point_id = uuid4()
    command = ConfirmPartyContactPointCommand(
        organization_id=uuid4(),
        principal_id=uuid4(),
        party_id=party_id,
        contact_point_id=contact_point_id,
        idempotency_key="replay-confirm",
    )

    with pytest.raises(PartyContactPointNotFound) as not_found:
        await commands.confirm_party_contact_point(command)

    assert not_found.value.party_id == party_id
    assert not_found.value.contact_point_id == contact_point_id
