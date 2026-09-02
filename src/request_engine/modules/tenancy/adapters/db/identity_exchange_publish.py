"""PostgreSQL publication adapter for S0d portable identity profiles."""

from typing import cast

from request_engine.modules.tenancy.adapters.db.identity_exchange_sql import (
    LOCAL_DOCUMENT,
    PUBLISH,
)
from request_engine.modules.tenancy.application.identity_exchange import (
    PublishPortableProfileCommand,
)
from request_engine.modules.tenancy.application.identity_exchange_errors import (
    IdentityExchangeProfileInvalid,
    IdentityExchangeUnavailable,
)
from request_engine.modules.tenancy.domain.identity_exchange import (
    ScopedIdentityDocument,
    identity_document_fingerprint,
)
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)

_CAPABILITY = "identity_exchange.publish"


class PostgresPortableProfilePublisher:
    def __init__(self, session_factory: SessionFactory, fingerprint_key: bytes | None) -> None:
        self._session_factory = session_factory
        self._fingerprint_key = fingerprint_key

    async def publish_portable_profile(self, command: PublishPortableProfileCommand) -> None:
        authority = command.document_authority
        if authority is None:
            raise IdentityExchangeProfileInvalid("scoped document authority is required")
        fingerprint = command_fingerprint(
            _CAPABILITY,
            {
                "party_id": str(command.party_id),
                "document_kind": command.document_kind,
                "document_authority": authority,
                "consented_fields": list(command.consented_fields),
                "proof_kind": command.proof_kind,
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability=_CAPABILITY,
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return
            value = (
                await session.execute(
                    LOCAL_DOCUMENT,
                    {
                        "organization_id": command.organization_id,
                        "party_id": command.party_id,
                        "kind": command.document_kind,
                        "authority": authority,
                    },
                )
            ).scalar_one_or_none()
            if value is None:
                raise IdentityExchangeProfileInvalid(
                    "active Party with requested scoped identity document is required"
                )
            try:
                identity_fingerprint = identity_document_fingerprint(
                    self._fingerprint_key,
                    ScopedIdentityDocument(
                        command.document_kind,
                        authority,
                        cast(str, value),
                    ),
                )
            except RuntimeError as error:
                raise IdentityExchangeUnavailable(str(error)) from None
            published = (
                await session.execute(
                    PUBLISH,
                    {
                        "party_id": command.party_id,
                        "kind": command.document_kind,
                        "authority": authority,
                        "fingerprint": identity_fingerprint,
                        "consented_fields": list(command.consented_fields),
                        "principal_id": command.principal_id,
                    },
                )
            ).scalar_one()
            if published is not True:
                raise RuntimeError("portable profile publication did not complete")
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name=_CAPABILITY,
                aggregate_kind="PartyPortableProfile",
                aggregate_id=command.party_id,
                idempotency_id=idempotency_id,
                details={
                    "document_kind": command.document_kind,
                    "document_authority": authority,
                    "proof_kind": command.proof_kind,
                    "consented_fields": list(command.consented_fields),
                },
            )
            await complete_idempotency(
                session,
                idempotency_id,
                {"published": True},
            )
