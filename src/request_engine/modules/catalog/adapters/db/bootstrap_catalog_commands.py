from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from request_engine.modules.catalog.application.commands.bootstrap_catalog import (
    CreateOfferingCommand,
    CreateResourceCapabilityCommand,
    OfferingBootstrapState,
    ResourceCapabilityState,
)
from request_engine.modules.catalog.application.errors import CatalogConfigurationConflict
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.security.operational_authority import (
    MANAGE_COMMERCIAL_TERMS_SCOPE,
    MANAGE_OPERATIONAL_PROFILE_SCOPE,
    require_operational_authority,
)


class PostgresCatalogBootstrapCommands:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def create_resource_capability(
        self, command: CreateResourceCapabilityCommand
    ) -> ResourceCapabilityState:
        fingerprint = command_fingerprint(
            "catalog.create_resource_capability",
            {
                "authority_party_id": command.authority_party_id,
                "capability_key": command.capability_key.strip(),
                "display_name": command.display_name.strip(),
            },
        )
        try:
            async with tenant_transaction(self._session_factory, command.organization_id) as session:
                idem, replay = await acquire_idempotency(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    capability="catalog.create_resource_capability",
                    idempotency_key=command.idempotency_key,
                    fingerprint=fingerprint,
                )
                if replay is not None:
                    payload = cast(dict[str, object], replay["resource_capability"])
                    return ResourceCapabilityState(
                        capability_id=UUID(cast(str, payload["capability_id"])),
                        capability_key=cast(str, payload["capability_key"]),
                        display_name=cast(str, payload["display_name"]),
                    )
                authority = await require_operational_authority(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    authority_party_id=command.authority_party_id,
                    scope_key=MANAGE_OPERATIONAL_PROFILE_SCOPE,
                )
                row = (
                    (
                        await session.execute(
                            text(
                                """
                                INSERT INTO request_engine.resource_capabilities (
                                    organization_id, capability_key, display_name
                                ) VALUES (:organization_id, :capability_key, :display_name)
                                RETURNING id, capability_key, display_name
                                """
                            ),
                            {
                                "organization_id": command.organization_id,
                                "capability_key": command.capability_key.strip(),
                                "display_name": command.display_name.strip(),
                            },
                        )
                    )
                    .mappings()
                    .one()
                )
                state = ResourceCapabilityState(
                    capability_id=cast(UUID, row["id"]),
                    capability_key=cast(str, row["capability_key"]),
                    display_name=cast(str, row["display_name"]),
                )
                await append_audit(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    command_name="catalog.create_resource_capability",
                    aggregate_kind="ResourceCapability",
                    aggregate_id=state.capability_id,
                    idempotency_id=idem,
                    details={"authority": authority.audit_details(), "capability_key": state.capability_key},
                )
                payload = {
                    "capability_id": str(state.capability_id),
                    "capability_key": state.capability_key,
                    "display_name": state.display_name,
                }
                await complete_idempotency(session, idem, {"resource_capability": payload})
                return state
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) == "23505":
                raise CatalogConfigurationConflict("Resource capability key already exists") from None
            raise

    async def create_offering(self, command: CreateOfferingCommand) -> OfferingBootstrapState:
        fingerprint = command_fingerprint(
            "catalog.create_offering",
            {
                "authority_party_id": command.authority_party_id,
                "offering_key": command.offering_key.strip(),
                "display_name": command.display_name.strip(),
                "description": command.description,
                "duration_minutes": command.duration_minutes,
                "bookable": command.bookable,
                "requestable": command.requestable,
                "slot_step_minutes": command.slot_step_minutes,
                "requirements": [
                    {"capability_id": item.capability_id, "quantity": item.quantity}
                    for item in command.requirements
                ],
            },
        )
        try:
            async with tenant_transaction(self._session_factory, command.organization_id) as session:
                idem, replay = await acquire_idempotency(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    capability="catalog.create_offering",
                    idempotency_key=command.idempotency_key,
                    fingerprint=fingerprint,
                )
                if replay is not None:
                    return _offering_state(cast(dict[str, object], replay["offering"]))
                authority = await require_operational_authority(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    authority_party_id=command.authority_party_id,
                    scope_key=MANAGE_COMMERCIAL_TERMS_SCOPE,
                )
                capability_ids = [item.capability_id for item in command.requirements]
                if capability_ids:
                    count = cast(
                        int,
                        (
                            await session.execute(
                                text(
                                    """
                                    SELECT count(*)
                                    FROM request_engine.resource_capabilities
                                    WHERE organization_id = :organization_id
                                      AND id = ANY(:capability_ids)
                                    """
                                ),
                                {
                                    "organization_id": command.organization_id,
                                    "capability_ids": capability_ids,
                                },
                            )
                        ).scalar_one(),
                    )
                    if count != len(capability_ids):
                        raise CatalogConfigurationConflict(
                            "Offering requirements contain an unknown tenant capability"
                        )
                offering_id = cast(
                    UUID,
                    (
                        await session.execute(
                            text(
                                """
                                INSERT INTO request_engine.offerings (
                                    organization_id, offering_key, display_name, description
                                ) VALUES (
                                    :organization_id, :offering_key, :display_name, :description
                                ) RETURNING id
                                """
                            ),
                            {
                                "organization_id": command.organization_id,
                                "offering_key": command.offering_key.strip(),
                                "display_name": command.display_name.strip(),
                                "description": command.description,
                            },
                        )
                    ).scalar_one(),
                )
                version_id = cast(
                    UUID,
                    (
                        await session.execute(
                            text(
                                """
                                INSERT INTO request_engine.offering_versions (
                                    organization_id, offering_id, version, duration_minutes,
                                    bookable, requestable, booking_policy, public_data
                                ) VALUES (
                                    :organization_id, :offering_id, 1, :duration_minutes,
                                    :bookable, :requestable,
                                    jsonb_build_object('slot_step_minutes', :slot_step_minutes),
                                    '{}'::jsonb
                                ) RETURNING id
                                """
                            ),
                            {
                                "organization_id": command.organization_id,
                                "offering_id": offering_id,
                                "duration_minutes": command.duration_minutes,
                                "bookable": command.bookable,
                                "requestable": command.requestable,
                                "slot_step_minutes": command.slot_step_minutes,
                            },
                        )
                    ).scalar_one(),
                )
                requirement_ids: list[UUID] = []
                for ordinal, item in enumerate(command.requirements, start=1):
                    requirement_ids.append(
                        cast(
                            UUID,
                            (
                                await session.execute(
                                    text(
                                        """
                                        INSERT INTO request_engine.offering_resource_requirements (
                                            organization_id, offering_version_id,
                                            capability_id, ordinal, quantity
                                        ) VALUES (
                                            :organization_id, :version_id,
                                            :capability_id, :ordinal, :quantity
                                        ) RETURNING id
                                        """
                                    ),
                                    {
                                        "organization_id": command.organization_id,
                                        "version_id": version_id,
                                        "capability_id": item.capability_id,
                                        "ordinal": ordinal,
                                        "quantity": item.quantity,
                                    },
                                )
                            ).scalar_one(),
                        )
                    )
                state = OfferingBootstrapState(
                    offering_id=offering_id,
                    offering_version_id=version_id,
                    offering_key=command.offering_key.strip(),
                    version=1,
                    requirement_ids=tuple(requirement_ids),
                )
                await append_audit(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    command_name="catalog.create_offering",
                    aggregate_kind="Offering",
                    aggregate_id=offering_id,
                    idempotency_id=idem,
                    details={
                        "authority": authority.audit_details(),
                        "offering_version_id": str(version_id),
                        "requirement_count": len(requirement_ids),
                    },
                )
                await complete_idempotency(session, idem, {"offering": _offering_json(state)})
                return state
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) == "23505":
                raise CatalogConfigurationConflict("Offering conflicts with tenant catalog") from None
            raise


def _offering_json(state: OfferingBootstrapState) -> dict[str, object]:
    return {
        "offering_id": str(state.offering_id),
        "offering_version_id": str(state.offering_version_id),
        "offering_key": state.offering_key,
        "version": state.version,
        "requirement_ids": [str(value) for value in state.requirement_ids],
    }


def _offering_state(value: dict[str, object]) -> OfferingBootstrapState:
    return OfferingBootstrapState(
        offering_id=UUID(cast(str, value["offering_id"])),
        offering_version_id=UUID(cast(str, value["offering_version_id"])),
        offering_key=cast(str, value["offering_key"]),
        version=cast(int, value["version"]),
        requirement_ids=tuple(UUID(item) for item in cast(list[str], value["requirement_ids"])),
    )
