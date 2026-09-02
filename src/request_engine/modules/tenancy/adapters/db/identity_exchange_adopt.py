"""Atomic PostgreSQL adoption of a portable identity into a normal local Party."""

from collections.abc import Mapping
from typing import cast

from sqlalchemy.exc import IntegrityError

from request_engine.modules.tenancy.adapters.db.identity_exchange_adopt_tx import (
    write_identity_adoption,
)
from request_engine.modules.tenancy.adapters.db.identity_exchange_codec import (
    adoption_from_json,
    adoption_to_json,
)
from request_engine.modules.tenancy.adapters.db.identity_exchange_conflicts import (
    existing_adopted_party,
    is_identity_already_adopted_violation,
)
from request_engine.modules.tenancy.adapters.db.party_registry_conflicts import raise_document_conflict
from request_engine.modules.tenancy.application.identity_exchange import AdoptPortableIdentityCommand
from request_engine.modules.tenancy.application.identity_exchange_errors import (
    IdentityExchangeAlreadyAdopted,
    IdentityExchangeUnavailable,
)
from request_engine.modules.tenancy.contracts.identity_exchange import IdentityAdoptionResult
from request_engine.modules.tenancy.contracts.party_registry import PartyDocumentInput
from request_engine.modules.tenancy.domain.identity_exchange import (
    ScopedIdentityDocument,
    identity_document_fingerprint,
)
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
        authority = command.document_authority
        if authority is None:
            raise IdentityExchangeUnavailable("scoped document authority is required")
        document = ScopedIdentityDocument(command.document_kind, authority, command.document_value)
        try:
            fingerprint = identity_document_fingerprint(self._fingerprint_key, document)
        except RuntimeError as error:
            raise IdentityExchangeUnavailable(str(error)) from None
        idem_fingerprint = command_fingerprint(
            _CAPABILITY,
            {
                "candidate_ref": str(command.candidate_ref),
                "document_kind": document.kind,
                "document_authority": document.authority,
                "fingerprint": fingerprint,
                "display_name": command.display_name,
                "consented_fields": list(command.consented_fields),
                "proof_kind": command.proof_kind,
            },
        )
        documents = (PartyDocumentInput(document.kind, document.value, document.authority),)
        try:
            async with tenant_transaction(
                self._session_factory, command.organization_id
            ) as session:
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
                result = await write_identity_adoption(
                    session,
                    command,
                    fingerprint=fingerprint,
                    idempotency_id=idempotency_id,
                )
                await complete_idempotency(
                    session,
                    idempotency_id,
                    {"adoption": adoption_to_json(result)},
                )
                return result
        except IntegrityError as exc:
            if is_identity_already_adopted_violation(exc):
                existing_party_id = await existing_adopted_party(
                    self._session_factory,
                    command.organization_id,
                    command.candidate_ref,
                    command.principal_id,
                )
                if existing_party_id is not None:
                    raise IdentityExchangeAlreadyAdopted(existing_party_id) from None
            await raise_document_conflict(
                self._session_factory,
                command.organization_id,
                documents,
                exc,
            )
