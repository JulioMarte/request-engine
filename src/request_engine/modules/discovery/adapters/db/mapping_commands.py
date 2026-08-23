from typing import cast
from uuid import UUID

from request_engine.modules.discovery.adapters.db import (
    mapping_codec,
    mapping_persistence,
    mapping_store,
)
from request_engine.modules.discovery.application.commands.mapping import (
    MapOfferingToServiceClassificationCommand,
    OfferingServiceClassificationState,
)
from request_engine.modules.discovery.application.errors import DiscoveryConfigurationConflict
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


class PostgresDiscoveryMappingCommands:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def map_offering(
        self, command: MapOfferingToServiceClassificationCommand
    ) -> OfferingServiceClassificationState:
        key = command.classification_key.strip()
        if not key:
            raise ValueError("classification_key is required")
        fingerprint = command_fingerprint(
            "discovery.map_offering",
            {
                "authority_party_id": command.authority_party_id,
                "offering_id": command.offering_id,
                "classification_key": key,
                "expected_revision": command.expected_revision,
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idem_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="discovery.map_offering",
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
            classification = await mapping_store.active_classification(session, key)
            if classification is None:
                raise DiscoveryConfigurationConflict("service classification unavailable")
            if not await mapping_store.lock_offering(
                session, command.organization_id, command.offering_id
            ):
                raise DiscoveryConfigurationConflict("offering unavailable")
            current = await mapping_store.current_mapping(
                session, command.organization_id, command.offering_id
            )
            classification_id = cast(UUID, classification["id"])
            row = await mapping_persistence.persist_mapping(
                session, command, current, classification_id
            )
            state = OfferingServiceClassificationState(
                id=cast(UUID, row["id"]),
                offering_id=command.offering_id,
                service_classification_id=classification_id,
                classification_key=key,
                status="active",
                revision=cast(int, row["revision"]),
            )
            details: dict[str, object] = {
                "authority": authority.audit_details(),
                "classification_key": key,
            }
            if current is not None and cast(UUID, current["id"]) != state.id:
                details["superseded_mapping_id"] = str(current["id"])
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name="discovery.map_offering",
                aggregate_kind="OfferingServiceClassification",
                aggregate_id=state.id,
                idempotency_id=idem_id,
                details=details,
            )
            await complete_idempotency(
                session, idem_id, {"state": mapping_codec.state_to_json(state)}
            )
            return state
