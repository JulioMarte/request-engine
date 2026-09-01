"""The document conflict error carries the existing party's identity.

Before raising `PartyDocumentConflict` the adapter resolves the conflicting
active document row in a fresh tenant transaction: the loser of the unique
backstop must report which Party holds the value (id and display name). Fake
session inputs replace the idempotency record; no database is involved.
"""

from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from request_engine.modules.tenancy.adapters.db import party_registry_conflicts
from request_engine.modules.tenancy.adapters.db.party_registry_conflicts import (
    raise_document_conflict,
)
from request_engine.modules.tenancy.application.errors import PartyDocumentConflict
from request_engine.modules.tenancy.contracts.party_registry import PartyDocumentInput
from request_engine.platform.db.session import SessionFactory

_DOCUMENT_VALUE_UNIQUE = "party_identity_documents_active_value_uq"


class _DocumentViolation(Exception):
    sqlstate = "23505"

    def __str__(self) -> str:
        return f'duplicate key value violates unique constraint "{_DOCUMENT_VALUE_UNIQUE}"'


class _FakeResult:
    def __init__(self, row: dict[str, object] | None) -> None:
        self._row = row

    def mappings(self) -> "_FakeResult":
        return self

    def first(self) -> dict[str, object] | None:
        return self._row


class _FakeSession:
    def __init__(self, row: dict[str, object] | None) -> None:
        self._row = row

    async def execute(self, statement: object, params: object = None) -> _FakeResult:
        del statement, params
        return _FakeResult(self._row)


class _FakeTransaction:
    def __init__(self, session: object) -> None:
        self._session = session

    async def __aenter__(self) -> object:
        return self._session

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


def _conflict_error() -> IntegrityError:
    return IntegrityError("INSERT ...", {}, _DocumentViolation())


def _documents() -> tuple[PartyDocumentInput, ...]:
    return (PartyDocumentInput("cedula", "40212345678"),)


def _organization_id() -> UUID:
    return uuid4()


def _install_session(monkeypatch: pytest.MonkeyPatch, row: dict[str, object] | None) -> None:
    def fake_transaction(factory: object, organization_id: UUID) -> _FakeTransaction:
        del factory, organization_id
        return _FakeTransaction(_FakeSession(row))

    monkeypatch.setattr(party_registry_conflicts, "tenant_transaction", fake_transaction)


async def _resolve(monkeypatch: pytest.MonkeyPatch, row: dict[str, object] | None) -> None:
    _install_session(monkeypatch, row)
    await raise_document_conflict(
        cast(SessionFactory, object()), _organization_id(), _documents(), _conflict_error()
    )


@pytest.mark.asyncio
async def test_conflict_error_carries_existing_party_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing_party_id = uuid4()
    with pytest.raises(PartyDocumentConflict) as conflict:
        await _resolve(monkeypatch, {"party_id": existing_party_id, "display_name": "Alma Bien"})

    assert conflict.value.existing_party_id == existing_party_id
    assert conflict.value.existing_display_name == "Alma Bien"


@pytest.mark.asyncio
async def test_conflict_without_resolvable_row_reraises(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(IntegrityError):
        await _resolve(monkeypatch, None)


@pytest.mark.asyncio
async def test_unrelated_integrity_error_is_never_a_document_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = IntegrityError("INSERT ...", {}, Exception("check constraint violated"))
    _install_session(monkeypatch, None)
    with pytest.raises(IntegrityError):
        await raise_document_conflict(
            cast(SessionFactory, object()), _organization_id(), _documents(), error
        )
