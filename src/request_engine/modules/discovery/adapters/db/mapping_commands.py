from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.discovery.application.commands.mapping import (
    MapOfferingToServiceClassificationCommand,
    OfferingServiceClassificationState,
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
                return _state_from_json(cast(dict[str, object], replay["state"]))
            authority = await require_operational_authority(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                authority_party_id=command.authority_party_id,
                scope_key=MANAGE_DISCOVERY_SCOPE,
            )
            classification = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT id, classification_key
                            FROM request_engine.service_classifications
                            WHERE classification_key = :key AND status = 'active'
                            FOR SHARE
                            """
                        ),
                        {"key": key},
                    )
                )
                .mappings()
                .first()
            )
            if classification is None:
                raise DiscoveryConfigurationConflict("service classification unavailable")
            offering_exists = (
                await session.execute(
                    text(
                        """
                        SELECT 1 FROM request_engine.offerings
                        WHERE organization_id = :organization_id AND id = :offering_id
                        FOR SHARE
                        """
                    ),
                    {"organization_id": command.organization_id, "offering_id": command.offering_id},
                )
            ).scalar_one_or_none()
            if offering_exists is None:
                raise DiscoveryConfigurationConflict("offering unavailable")
            current = await _current_mapping(session, command.organization_id, command.offering_id)
            classification_id = cast(UUID, classification["id"])
            if current is None:
                if command.expected_revision is not None:
                    raise DiscoveryConfigurationConflict("mapping does not yet exist")
                row = (
                    (
                        await session.execute(
                            text(
                                """
                                INSERT INTO request_engine.offering_service_classifications (
                                    organization_id, offering_id, service_classification_id
                                ) VALUES (:organization_id, :offering_id, :classification_id)
                                RETURNING id, revision
                                """
                            ),
                            {
                                "organization_id": command.organization_id,
                                "offering_id": command.offering_id,
                                "classification_id": classification_id,
                            },
                        )
                    )
                    .mappings()
                    .one()
                )
            else:
                actual = cast(int, current["revision"])
                if command.expected_revision != actual:
                    raise DiscoveryRevisionConflict(cast(UUID, current["id"]), command.expected_revision or 0, actual)
                if cast(UUID, current["service_classification_id"]) == classification_id:
                    row = current
                else:
                    row = (
                        (
                            await session.execute(
                                text(
                                    """
                                    UPDATE request_engine.offering_service_classifications
                                    SET service_classification_id = :classification_id
                                    WHERE id = :id AND organization_id = :organization_id
                                    RETURNING id, revision
                                    """
                                ),
                                {"classification_id": classification_id, "id": current["id"], "organization_id": command.organization_id},
                            )
                        )
                        .mappings()
                        .one()
                    )
            state = OfferingServiceClassificationState(
                id=cast(UUID, row["id"]), offering_id=command.offering_id,
                service_classification_id=classification_id, classification_key=key,
                status="active", revision=cast(int, row["revision"]),
            )
            await append_audit(
                session, organization_id=command.organization_id, principal_id=command.principal_id,
                command_name="discovery.map_offering", aggregate_kind="OfferingServiceClassification",
                aggregate_id=state.id, idempotency_id=idem_id,
                details={"authority": authority.audit_details(), "classification_key": key},
            )
            await complete_idempotency(session, idem_id, {"state": _state_to_json(state)})
            return state


async def _current_mapping(session: object, organization_id: UUID, offering_id: UUID):
    return (
        (await session.execute(text("SELECT id, service_classification_id, revision FROM request_engine.offering_service_classifications WHERE organization_id=:organization_id AND offering_id=:offering_id AND status='active' FOR UPDATE"), {"organization_id": organization_id, "offering_id": offering_id})).mappings().first()
    )


def _state_to_json(state: OfferingServiceClassificationState) -> dict[str, object]:
    return {"id": str(state.id), "offering_id": str(state.offering_id), "service_classification_id": str(state.service_classification_id), "classification_key": state.classification_key, "status": state.status, "revision": state.revision}


def _state_from_json(value: dict[str, object]) -> OfferingServiceClassificationState:
    return OfferingServiceClassificationState(id=UUID(cast(str, value["id"])), offering_id=UUID(cast(str, value["offering_id"])), service_classification_id=UUID(cast(str, value["service_classification_id"])), classification_key=cast(str, value["classification_key"]), status=cast(str, value["status"]), revision=cast(int, value["revision"]))
