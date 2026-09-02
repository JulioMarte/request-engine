"""In-transaction S0d candidate consumption, Party creation and binding."""

from collections.abc import Mapping
from typing import cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.tenancy.adapters.db.identity_exchange_codec import (
    portable_contacts,
    portable_display_name,
    portable_insurance,
)
from request_engine.modules.tenancy.adapters.db.identity_exchange_sql import (
    BIND_CANDIDATE,
    CONSUME_CANDIDATE,
)
from request_engine.modules.tenancy.adapters.db.party_registration_write import (
    write_registered_party,
)
from request_engine.modules.tenancy.application.commands.register_party import (
    RegisterPartyCommand,
)
from request_engine.modules.tenancy.application.identity_exchange import (
    AdoptPortableIdentityCommand,
)
from request_engine.modules.tenancy.application.identity_exchange_errors import (
    IdentityExchangeCandidateInvalid,
    IdentityExchangeProfileInvalid,
)
from request_engine.modules.tenancy.contracts.identity_exchange import IdentityAdoptionResult
from request_engine.modules.tenancy.contracts.party_registry import PartyDocumentInput


async def write_identity_adoption(
    session: AsyncSession,
    command: AdoptPortableIdentityCommand,
    *,
    fingerprint: str,
    idempotency_id: UUID,
) -> IdentityAdoptionResult:
    authority = command.document_authority
    if authority is None:
        raise IdentityExchangeCandidateInvalid("scoped document authority is required")
    row = (
        await session.execute(
            CONSUME_CANDIDATE,
            {
                "candidate_ref": command.candidate_ref,
                "kind": command.document_kind,
                "authority": authority,
                "fingerprint": fingerprint,
                "principal_id": command.principal_id,
            },
        )
    ).mappings().first()
    if row is None:
        raise IdentityExchangeCandidateInvalid("candidate is invalid, expired or consumed")
    profile = cast(Mapping[str, object], row["profile"])
    try:
        display_name = portable_display_name(profile)
        contacts = portable_contacts(profile, command.consented_fields)
    except ValueError as error:
        raise IdentityExchangeProfileInvalid(str(error)) from None
    register_command = RegisterPartyCommand(
        organization_id=command.organization_id,
        principal_id=command.principal_id,
        display_name=display_name,
        source_kind=command.source_kind,
        idempotency_key=command.idempotency_key,
        contact_points=contacts,
        documents=(
            PartyDocumentInput(command.document_kind, command.document_value, authority),
        ),
        platform=command.platform,
        technical_principal_id=command.technical_principal_id,
    )
    party = await write_registered_party(
        session,
        register_command,
        command_name="identity_exchange.adopt",
        idempotency_id=idempotency_id,
        audit_details={
            "candidate_ref": str(command.candidate_ref),
            "document_kind": command.document_kind,
            "document_authority": authority,
            "proof_kind": command.proof_kind,
            "consented_fields": list(command.consented_fields),
        },
    )
    binding_id = cast(
        UUID,
        (
            await session.execute(
                BIND_CANDIDATE,
                {
                    "candidate_ref": command.candidate_ref,
                    "party_id": party.party_id,
                    "consented_fields": list(command.consented_fields),
                    "principal_id": command.principal_id,
                },
            )
        ).scalar_one(),
    )
    insurance = portable_insurance(profile, command.consented_fields)
    return IdentityAdoptionResult(
        party=party,
        binding_id=binding_id,
        portable_insurance_identifiers=insurance,
    )
