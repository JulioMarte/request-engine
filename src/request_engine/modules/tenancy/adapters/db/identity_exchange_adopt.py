"""Atomic PostgreSQL adoption of a portable identity into a normal local Party."""

from collections.abc import Mapping
from typing import cast
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from request_engine.modules.tenancy.adapters.db.identity_exchange_codec import (
    adoption_from_json,
    adoption_to_json,
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
from request_engine.modules.tenancy.adapters.db.party_registry_conflicts import (
    raise_document_conflict,
)
from request_engine.modules.tenancy.application.commands.register_party import RegisterPartyCommand
from request_engine.modules.tenancy.application.identity_exchange import AdoptPortableIdentityCommand
from request_engine.modules.tenancy.application.identity_exchange_errors import (
    IdentityExchangeCandidateInvalid,
    IdentityExchangeProfileInvalid,
    IdentityExchangeUnavailable,
)
from request_engine.modules.tenancy.contracts.identity_exchange import IdentityAdoptionResult
from request_engine.modules.tenancy.contracts.party_registry import PartyDocumentInput
from request_engine.modules.tenancy.domain.identity_exchange import cedula_fingerprint
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)

_CAPABILITY = "identity_exchange.adopt"


class PostgresPortableIdentityAdopter:
    def __init__(self, session_factory: SessionFactory, fingerprint_key: bytes | None) -> None:
        self._session_factory = session_factory
        self._fingerprint_key = fingerprint_key

    async def adopt_portable_identity(
        self,
        command: AdoptPortableIdentityCommand,
    ) -> IdentityAdoptionResult:
        try:
            fingerprint = cedula_fingerprint(self._fingerprint_key, command.document_value)
        except RuntimeError as error:
            raise IdentityExchangeUnavailable(str(error)) from None
        idem_fingerprint = command_fingerprint(
            _CAPABILITY,
            {
                "candidate_ref": str(command.candidate_ref),
                "fingerprint": fingerprint,
                "consented_fields": list(command.consented_fields),
                "proof_kind": command.proof_kind,
            },
        )
        documents = (PartyDocumentInput("cedula", command.document_value),)
        try:
            async with tenant_transaction(self._session_factory, command.organization_id) as session:
                idempotency_id, replay = await acquire_idempotency(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    capability=_CAPABILITY,
                    idempotency_key=command.idempotency_key,
                    fingerprint=idem_fingerprint,
                )
                if replay is not None:
                    return adoption_from_json(cast(Mapping[str, object], replay["adoption"]))
                row = (
                    await session.execute(
                        CONSUME_CANDIDATE,
                        {
                            "candidate_ref": command.candidate_ref,
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
                    documents=documents,
                    platform=command.platform,
                    technical_principal_id=command.technical_principal_id,
                )
                party = await write_registered_party(
                    session,
                    register_command,
                    command_name=_CAPABILITY,
                    idempotency_id=idempotency_id,
                    audit_details={
                        "candidate_ref": str(command.candidate_ref),
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
                result = IdentityAdoptionResult(
                    party=party,
                    binding_id=binding_id,
                    portable_insurance_identifiers=portable_insurance(
                        profile, command.consented_fields
                    ),
                )
                await complete_idempotency(
                    session,
                    idempotency_id,
                    {"adoption": adoption_to_json(result)},
                )
                return result
        except IntegrityError as exc:
            await raise_document_conflict(
                self._session_factory,
                command.organization_id,
                documents,
                exc,
            )
