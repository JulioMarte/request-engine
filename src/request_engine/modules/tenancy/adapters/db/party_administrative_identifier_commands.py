"""PostgreSQL command adapter for Party administrative identifiers."""

from collections.abc import Mapping
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.tenancy.adapters.db.party_administrative_identifier_codec import (
    identifier_from_json,
    identifier_from_mapping,
    identifier_to_json,
)
from request_engine.modules.tenancy.adapters.db.party_administrative_identifier_sql import (
    FIND_IDENTIFIER,
    INSERT_IDENTIFIER,
    fingerprint_values,
    sql_values,
)
from request_engine.modules.tenancy.adapters.db.party_registry_rows import attribution_values
from request_engine.modules.tenancy.adapters.db.party_registry_store import lock_party
from request_engine.modules.tenancy.application.administrative_identifier_errors import (
    PartyAdministrativeIdentifierConflict,
)
from request_engine.modules.tenancy.application.commands.add_party_administrative_identifier import (
    AddPartyAdministrativeIdentifierCommand,
)
from request_engine.modules.tenancy.contracts.party_administrative_identifiers import (
    PartyAdministrativeIdentifier,
)
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)

_CAPABILITY = "parties.add_administrative_identifier"


class PostgresPartyAdministrativeIdentifierCommands:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def add_party_administrative_identifier(
        self,
        command: AddPartyAdministrativeIdentifierCommand,
    ) -> PartyAdministrativeIdentifier:
        fingerprint = command_fingerprint(_CAPABILITY, fingerprint_values(command))
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
                payload = cast(Mapping[str, object], replay["identifier"])
                return identifier_from_json(payload)

            await lock_party(session, command.organization_id, command.party_id)
            params = sql_values(command)
            row = (await session.execute(INSERT_IDENTIFIER, params)).mappings().first()
            identifier = (
                identifier_from_mapping(row)
                if row is not None
                else await self._resolve_conflict(session, command, params)
            )
            if row is not None:
                await append_audit(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    command_name=_CAPABILITY,
                    aggregate_kind="PartyAdministrativeIdentifier",
                    aggregate_id=identifier.identifier_id,
                    idempotency_id=idempotency_id,
                    details={
                        "party_id": str(command.party_id),
                        "kind": command.kind,
                        "issuer": command.issuer,
                        "normalized_value": command.normalized_value,
                        **attribution_values(command),
                    },
                )
            await complete_idempotency(
                session,
                idempotency_id,
                {"identifier": identifier_to_json(identifier)},
            )
            return identifier

    async def _resolve_conflict(
        self,
        session: AsyncSession,
        command: AddPartyAdministrativeIdentifierCommand,
        params: dict[str, object],
    ) -> PartyAdministrativeIdentifier:
        row = (await session.execute(FIND_IDENTIFIER, params)).mappings().first()
        if row is None:
            raise RuntimeError("administrative identifier conflict could not be resolved")
        identifier = identifier_from_mapping(row)
        if (
            identifier.party_id == command.party_id
            and identifier.normalized_value == command.normalized_value
        ):
            return identifier
        raise PartyAdministrativeIdentifierConflict(
            kind=command.kind,
            issuer=command.issuer,
            normalized_value=command.normalized_value,
            existing_party_id=identifier.party_id,
        )
