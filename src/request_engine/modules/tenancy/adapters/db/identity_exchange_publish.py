"""PostgreSQL publication adapter for S0d portable identity profiles."""

from typing import cast
from uuid import UUID

from request_engine.modules.tenancy.adapters.db.identity_exchange_sql import LOCAL_CEDULA, PUBLISH
from request_engine.modules.tenancy.application.identity_exchange import PublishPortableProfileCommand
from request_engine.modules.tenancy.application.identity_exchange_errors import (
    IdentityExchangeProfileInvalid,
    IdentityExchangeUnavailable,
)
from request_engine.modules.tenancy.domain.identity_exchange import cedula_fingerprint
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

    async def publish_portable_profile(self, command: PublishPortableProfileCommand) -> UUID:
        fingerprint = command_fingerprint(
            _CAPABILITY,
            {
                "party_id": str(command.party_id),
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
                return UUID(str(replay["portable_person_id"]))
            cedula = (
                await session.execute(
                    LOCAL_CEDULA,
                    {"organization_id": command.organization_id, "party_id": command.party_id},
                )
            ).scalar_one_or_none()
            if cedula is None:
                raise IdentityExchangeProfileInvalid("active Party with cédula is required")
            try:
                identity_fingerprint = cedula_fingerprint(
                    self._fingerprint_key,
                    cast(str, cedula),
                )
            except RuntimeError as error:
                raise IdentityExchangeUnavailable(str(error)) from None
            portable_person_id = cast(
                UUID,
                (
                    await session.execute(
                        PUBLISH,
                        {
                            "party_id": command.party_id,
                            "fingerprint": identity_fingerprint,
                            "consented_fields": list(command.consented_fields),
                            "principal_id": command.principal_id,
                        },
                    )
                ).scalar_one(),
            )
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name=_CAPABILITY,
                aggregate_kind="PortablePerson",
                aggregate_id=portable_person_id,
                idempotency_id=idempotency_id,
                details={
                    "party_id": str(command.party_id),
                    "proof_kind": command.proof_kind,
                    "consented_fields": list(command.consented_fields),
                },
            )
            await complete_idempotency(
                session,
                idempotency_id,
                {"portable_person_id": str(portable_person_id)},
            )
            return portable_person_id
