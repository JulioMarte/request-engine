"""PostgreSQL command adapter for Party administrative identifiers."""

from collections.abc import Mapping
from typing import cast

from sqlalchemy import text

from request_engine.modules.tenancy.adapters.db.party_administrative_identifier_codec import (
    identifier_from_json,
    identifier_from_mapping,
    identifier_to_json,
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
_INSERT = text("""
INSERT INTO request_engine.party_administrative_identifiers
 (organization_id, party_id, kind, issuer, normalized_issuer, value, normalized_value,
  created_by_principal_id, source_kind, platform, relay_principal_id)
VALUES
 (:organization_id, :party_id, :kind, :issuer, :normalized_issuer, :value, :normalized_value,
  :principal_id, :source_kind, :platform, :relay_principal_id)
ON CONFLICT DO NOTHING
RETURNING id, party_id, kind, issuer, normalized_issuer, value, normalized_value, active
""")
_FIND = text("""
SELECT id, party_id, kind, issuer, normalized_issuer, value, normalized_value, active
FROM request_engine.party_administrative_identifiers
WHERE organization_id = :organization_id AND kind = :kind AND normalized_issuer = :normalized_issuer
  AND active AND (normalized_value = :normalized_value OR party_id = :party_id)
ORDER BY (normalized_value = :normalized_value) DESC
LIMIT 1
""")


class PostgresPartyAdministrativeIdentifierCommands:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def add_party_administrative_identifier(
        self, command: AddPartyAdministrativeIdentifierCommand
    ) -> PartyAdministrativeIdentifier:
        fingerprint = command_fingerprint(_CAPABILITY, _fingerprint(command))
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idem_id, replay = await acquire_idempotency(
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
            params = _sql_params(command)
            row = (await session.execute(_INSERT, params)).mappings().first()
            if row is None:
                existing = (await session.execute(_FIND, params)).mappings().first()
                if existing is None:
                    raise RuntimeError("administrative identifier conflict could not be resolved")
                identifier = identifier_from_mapping(existing)
                if (
                    identifier.party_id != command.party_id
                    or identifier.normalized_value != command.normalized_value
                ):
                    raise PartyAdministrativeIdentifierConflict(
                        kind=command.kind,
                        issuer=command.issuer,
                        normalized_value=command.normalized_value,
                        existing_party_id=identifier.party_id,
                    )
            else:
                identifier = identifier_from_mapping(row)
                await append_audit(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    command_name=_CAPABILITY,
                    aggregate_kind="PartyAdministrativeIdentifier",
                    aggregate_id=identifier.identifier_id,
                    idempotency_id=idem_id,
                    details={"party_id": str(command.party_id), "kind": command.kind,
                             "issuer": command.issuer, "normalized_value": command.normalized_value},
                )
            await complete_idempotency(session, idem_id, {"identifier": identifier_to_json(identifier)})
            return identifier


def _fingerprint(command: AddPartyAdministrativeIdentifierCommand) -> dict[str, object]:
    return {"party_id": str(command.party_id), "kind": command.kind, "issuer": command.issuer,
            "normalized_issuer": command.normalized_issuer, "value": command.value,
            "normalized_value": command.normalized_value, "source_kind": command.source_kind.value,
            "platform": command.platform}


def _sql_params(command: AddPartyAdministrativeIdentifierCommand) -> dict[str, object]:
    return {"organization_id": command.organization_id, "party_id": command.party_id,
            "principal_id": command.principal_id, "kind": command.kind, "issuer": command.issuer,
            "normalized_issuer": command.normalized_issuer, "value": command.value,
            "normalized_value": command.normalized_value, **attribution_values(command)}
