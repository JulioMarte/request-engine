"""Only the intended unique violations map to typed party registry conflicts.

SQLSTATE 23505 on the document active-value backstop / the contact-point
uniqueness constraint maps to the typed conflict; any other integrity failure
re-raises. A blanket `except IntegrityError` would disguise unrelated database
failures as business conflicts, so these proofs turn red if the narrowing
widens again.
"""

from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from request_engine.modules.tenancy.adapters.db import (
    party_contact_point_commands,
    party_registry_conflicts,
)
from request_engine.modules.tenancy.adapters.db.party_contact_point_commands import (
    PostgresPartyContactPointCommands,
)
from request_engine.modules.tenancy.application.commands.add_party_contact_point import (
    AddPartyContactPointCommand,
)
from request_engine.modules.tenancy.application.errors import PartyContactPointExists
from request_engine.modules.tenancy.contracts.party_registry import RegisteredVia
from request_engine.platform.db.session import SessionFactory

_DOCUMENT_CONSTRAINT = "party_identity_documents_active_value_uq"
_CONTACT_CONSTRAINT = "party_contact_points_organization_id_party_id_channel_norma_key"


class _FakeUniqueViolation(Exception):
    def __init__(
        self,
        sqlstate: str | None,
        constraint: str | None = None,
        *,
        message: str = "",
    ) -> None:
        super().__init__(message or "unique violation")
        self.sqlstate = sqlstate
        if constraint is not None:
            self.diag = SimpleNamespace(constraint_name=constraint)
        self._message = message

    def __str__(self) -> str:
        return self._message or super().__str__()


class _FailingTransaction:
    def __init__(self, error: IntegrityError) -> None:
        self._error = error

    async def __aenter__(self) -> object:
        raise self._error

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


def _integrity_error(sqlstate: str | None, constraint: str | None = None) -> IntegrityError:
    return IntegrityError("INSERT ...", {}, _FakeUniqueViolation(sqlstate, constraint))


def _asyncpg_style_error(constraint: str) -> IntegrityError:
    # asyncpg: sqlstate attribute only, constraint name inside the message text.
    message = f'duplicate key value violates unique constraint "{constraint}"'
    return IntegrityError("INSERT ...", {}, _FakeUniqueViolation("23505", message=message))


def test_only_the_document_active_value_backstop_maps_to_conflict() -> None:
    assert party_registry_conflicts.is_document_value_violation(
        _integrity_error("23505", _DOCUMENT_CONSTRAINT)
    )
    assert not party_registry_conflicts.is_document_value_violation(
        _integrity_error("23505", "party_identity_documents_one_active_per_kind_uq")
    )
    assert not party_registry_conflicts.is_document_value_violation(
        _integrity_error("23000", _DOCUMENT_CONSTRAINT)
    )
    assert not party_registry_conflicts.is_document_value_violation(_integrity_error("23514", None))


def test_only_the_contact_point_constraint_maps_to_conflict() -> None:
    assert party_registry_conflicts.is_contact_point_violation(
        _integrity_error("23505", _CONTACT_CONSTRAINT)
    )
    assert not party_registry_conflicts.is_contact_point_violation(
        _integrity_error("23505", "party_contact_points_organization_id_id_key")
    )
    assert not party_registry_conflicts.is_contact_point_violation(
        _integrity_error("23000", _CONTACT_CONSTRAINT)
    )


def test_constraint_matching_falls_back_to_message_text_without_diag() -> None:
    assert party_registry_conflicts.is_document_value_violation(
        _asyncpg_style_error(_DOCUMENT_CONSTRAINT)
    )
    assert not party_registry_conflicts.is_document_value_violation(
        _asyncpg_style_error("party_identity_documents_one_active_per_kind_uq")
    )
    assert party_registry_conflicts.is_contact_point_violation(
        _asyncpg_style_error(_CONTACT_CONSTRAINT)
    )
    assert not party_registry_conflicts.is_contact_point_violation(
        _asyncpg_style_error("party_contact_points_organization_id_id_key")
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("constraint", "maps_to_conflict"),
    [
        (_CONTACT_CONSTRAINT, True),
        ("party_contact_points_organization_id_id_key", False),
    ],
)
async def test_add_contact_point_narrows_integrity_errors(
    monkeypatch: pytest.MonkeyPatch, constraint: str, maps_to_conflict: bool
) -> None:
    error = _integrity_error("23505", constraint)

    def fake_transaction(factory: object, organization_id: object) -> _FailingTransaction:
        del factory, organization_id
        return _FailingTransaction(error)

    monkeypatch.setattr(party_contact_point_commands, "tenant_transaction", fake_transaction)
    commands = PostgresPartyContactPointCommands(cast(SessionFactory, object()))
    command = AddPartyContactPointCommand(
        organization_id=uuid4(),
        principal_id=uuid4(),
        party_id=uuid4(),
        channel="whatsapp",
        value="+18095550110",
        registered_via=RegisteredVia.BOT,
        idempotency_key="narrowing",
    )

    expected = PartyContactPointExists if maps_to_conflict else IntegrityError
    with pytest.raises(expected):
        await commands.add_party_contact_point(command)
