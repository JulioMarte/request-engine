from typing import cast
from uuid import UUID

from request_engine.modules.discovery.adapters.db import mapping_codec, mapping_revoke_store
from request_engine.modules.discovery.application.commands.mapping import (
    OfferingServiceClassificationState,
)
from request_engine.modules.discovery.application.commands.revoke_mapping import (
    RevokeOfferingServiceClassificationCommand,
)
from request_engine.modules.discovery.application.errors import (
    DiscoveryConfigurationConflict,
    DiscoveryRevisionConflict,
)
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.security.operational_authority import (
    MANAGE_DISCOVERY_SCOPE,
    require_operational_authority,
)


class PostgresDiscoveryMappingRevokeCommands:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def revoke_mapping(
        self, command: RevokeOfferingServiceClassificationCommand
    ) -> OfferingServiceClassificationState:
        fingerprint = command_fingerprint(
            "discovery.revoke_mapping",
            {
                "authority_party_id": command.authority_party_id,
                "offering_id": command.offering_id,
                "expected_revision": command.expected_revision,
            },
        )
        async with tenant_transaction(
            self._session_factory, command.organization_id
        ) as session:
            idem_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="discovery.revoke_mapping",
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return mapping_codec.state_from_json(cast(dict[str, object], replay["state"]))
            authority = await require_operational_authority(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                authority_party_id=command.authority_party_id,
                scope_key=MANAGE_DISCOVERY_SCOPE,
            )
            current = await mapping_revoke_store.lock_mapping(
                session, command.organization_id, command.offering_id
            )
            if current is None:
                raise DiscoveryConfigurationConflict("offering classification unavailable")
            actual = cast(int, current["revision"])
            if actual != command.expected_revision:
                raise DiscoveryRevisionConflict(
                    cast(UUID, current["id"]), command.expected_revision, actual
                )
            updated = await mapping_revoke_store.revoke_mapping(
                session, command.organization_id, cast(UUID, current["id"])
            )
            state = OfferingServiceClassificationState(
                id=cast(UUID, current["id"]),
                offering_id=command.offering_id,
                service_classification_id=cast(UUID, current["service_classification_id"]),
                classification_key="",
                status="revoked",
                revision=cast(int, updated["revision"]),
            )
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name="discovery.revoke_mapping",
                aggregate_kind="OfferingServiceClassification",
                aggregate_id=state.id,
                idempotency_id=idem_id,
                details={"authority": authority.audit_details(), "previous_revision": actual},
            )
            await complete_idempotency(
                session, idem_id, {"state": mapping_codec.state_to_json(state)}
            )
            return state
