"""Command factories and adapter composition for the S0b party registry proofs."""

from uuid import UUID, uuid4

from request_engine.modules.tenancy.adapters.db.party_registry_commands import (
    PostgresPartyRegistryCommands,
)
from request_engine.modules.tenancy.application.commands.add_party_document import (
    AddPartyDocumentCommand,
)
from request_engine.modules.tenancy.application.commands.register_party import RegisterPartyCommand
from request_engine.modules.tenancy.application.commands.rename_party import RenamePartyCommand
from request_engine.modules.tenancy.contracts.party_registry import (
    PartyContactPointInput,
    PartyDocumentInput,
    PartySourceKind,
)
from request_engine.platform.db.session import SessionFactory


def registry_commands(session_factory: SessionFactory) -> PostgresPartyRegistryCommands:
    return PostgresPartyRegistryCommands(session_factory)


def register_command(
    organization_id: UUID,
    principal_id: UUID,
    *,
    display_name: str,
    whatsapp: str | None = None,
    phone: str | None = None,
    cedula: str | None = None,
    source_kind: PartySourceKind = PartySourceKind.OPERATOR,
) -> RegisterPartyCommand:
    contact_points: tuple[PartyContactPointInput, ...] = ()
    if whatsapp or phone:
        channels = [("whatsapp", whatsapp), ("phone", phone)]
        contact_points = tuple(
            PartyContactPointInput(channel, value)
            for channel, value in channels
            if value is not None
        )
    return RegisterPartyCommand(
        organization_id=organization_id,
        principal_id=principal_id,
        display_name=display_name,
        source_kind=source_kind,
        idempotency_key=f"register-{uuid4().hex}",
        contact_points=contact_points,
        documents=(PartyDocumentInput("cedula", cedula),) if cedula else (),
    )


def rename_command(
    organization_id: UUID,
    operator_principal_id: UUID,
    party_id: UUID,
    relay_principal_id: UUID,
) -> RenamePartyCommand:
    return RenamePartyCommand(
        organization_id=organization_id,
        principal_id=operator_principal_id,
        party_id=party_id,
        display_name="María González",
        idempotency_key=f"rename-{uuid4().hex}",
        source_kind=PartySourceKind.OPERATOR,
        platform="reception_web",
        technical_principal_id=relay_principal_id,
    )


def document_command(
    organization_id: UUID,
    principal_id: UUID,
    party_id: UUID,
    kind: str,
    value: str,
    *,
    authority: str | None = None,
) -> AddPartyDocumentCommand:
    return AddPartyDocumentCommand(
        organization_id=organization_id,
        principal_id=principal_id,
        party_id=party_id,
        kind=kind,
        value=value,
        authority=authority,
        source_kind=PartySourceKind.OPERATOR,
        idempotency_key=f"doc-{uuid4().hex}",
    )
