"""Application validation errors carry the caller's own raw values.

Multi-item registration bodies become debuggable: the 422 detail identifies
the offending item by its raw input value instead of only a rule description.
"""

from typing import cast
from uuid import uuid4

import pytest

from request_engine.modules.tenancy.application.commands.register_party import (
    RegisterPartyCommand,
    RegisterPartyHandler,
    register_party,
)
from request_engine.modules.tenancy.contracts.party_registry import (
    PartyContactPointInput,
    PartyDocumentInput,
    PartySourceKind,
)


class _PassthroughHandler:
    async def register_party(self, command: RegisterPartyCommand) -> object:
        return command


def _command(
    contact_points: tuple[PartyContactPointInput, ...] = (),
    documents: tuple[PartyDocumentInput, ...] = (),
) -> RegisterPartyCommand:
    return RegisterPartyCommand(
        organization_id=uuid4(),
        principal_id=uuid4(),
        display_name="Jose Perez",
        source_kind=PartySourceKind.OPERATOR,
        idempotency_key="validation",
        contact_points=contact_points,
        documents=documents,
    )


@pytest.mark.asyncio
async def test_invalid_document_error_includes_the_raw_value() -> None:
    with pytest.raises(ValueError) as raised:
        await register_party(
            cast(RegisterPartyHandler, _PassthroughHandler()),
            _command(documents=(PartyDocumentInput("cedula", "402-12"),)),
        )

    assert "402-12" in str(raised.value)


@pytest.mark.asyncio
async def test_invalid_contact_point_error_includes_the_raw_value() -> None:
    with pytest.raises(ValueError) as raised:
        await register_party(
            cast(RegisterPartyHandler, _PassthroughHandler()),
            _command(contact_points=(PartyContactPointInput("whatsapp", "+596123456"),)),
        )

    assert "+596123456" in str(raised.value)


@pytest.mark.asyncio
async def test_duplicate_contact_point_error_includes_the_raw_value() -> None:
    with pytest.raises(ValueError) as raised:
        await register_party(
            cast(RegisterPartyHandler, _PassthroughHandler()),
            _command(
                contact_points=(
                    PartyContactPointInput("phone", "(809) 555-1234"),
                    PartyContactPointInput("phone", "809-555-1234"),
                )
            ),
        )

    assert "809-555-1234" in str(raised.value)
    assert "+18095551234" in str(raised.value)


@pytest.mark.asyncio
async def test_duplicate_document_kind_error_includes_the_raw_value() -> None:
    with pytest.raises(ValueError) as raised:
        await register_party(
            cast(RegisterPartyHandler, _PassthroughHandler()),
            _command(
                documents=(
                    PartyDocumentInput("cedula", "40212345678"),
                    PartyDocumentInput("cedula", "402-1234567-8"),
                )
            ),
        )

    assert "402-1234567-8" in str(raised.value)
