import json
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

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
            async with tenant_transaction(
                self._session_factory, command.organization_id
            ) as session:
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
                    details={
                        "authority": authority.audit_details(),
                        "capability_key": state.capability_key,
                    },
                )
                await complete_idempotency(
                    session,
                    idem,
                    {
                        "resource_capability": {
                            "capability_id": str(state.capability_id),
                            "capability_key": state.capability_key,
                            "display_name": state.display_name,
                        }
                    },
                )
                return state
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) == "23505":
                raise CatalogConfigurationConflict(
                    "Resource capability key already exists"
                ) from None
            raise

    async def create_offering(self, command: CreateOfferingCommand) -> OfferingBootstrapState:
        booking_policy = _booking_policy(command)
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
                "booking_policy": booking_policy,
                "requirements": [
                    {"capability_id": item.capability_id, "quantity": item.quantity}
                    for item in command.requirements
                ],
            },
        )
        try:
            async with tenant_transaction(
                self._session_factory, command.organization_id
            ) as session:
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
                await _validate_capabilities(session, command)
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
                                    :bookable, :requestable, CAST(:booking_policy AS jsonb),
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
                                "booking_policy": json.dumps(booking_policy, separators=(",", ":")),
                            },
                        )
                    ).scalar_one(),
                )
                requirement_ids = await _insert_requirements(session, command, version_id)
                state = OfferingBootstrapState(
                    offering_id=offering_id,
                    offering_version_id=version_id,
                    offering_key=command.offering_key.strip(),
                    version=1,
                    requirement_ids=requirement_ids,
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
                        "reservation_communications_enabled": (
                            command.reservation_policy.confirmation
                            or bool(command.reservation_policy.reminders_before_minutes)
                            or command.reservation_policy.attendance_confirmation_required
                        ),
                    },
                )
                await complete_idempotency(session, idem, {"offering": _offering_json(state)})
                return state
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) == "23505":
                raise CatalogConfigurationConflict(
                    "Offering conflicts with tenant catalog"
                ) from None
            raise


async def _validate_capabilities(session: AsyncSession, command: CreateOfferingCommand) -> None:
    capability_ids = [item.capability_id for item in command.requirements]
    if not capability_ids:
        return
    result = await session.execute(
        text(
            """
            SELECT count(*)
            FROM request_engine.resource_capabilities
            WHERE organization_id = :organization_id
              AND id = ANY(CAST(:capability_ids AS uuid[]))
            """
        ),
        {
            "organization_id": command.organization_id,
            "capability_ids": [str(value) for value in capability_ids],
        },
    )
    if cast(int, result.scalar_one()) != len(capability_ids):
        raise CatalogConfigurationConflict(
            "Offering requirements contain an unknown tenant capability"
        )


async def _insert_requirements(
    session: AsyncSession,
    command: CreateOfferingCommand,
    version_id: UUID,
) -> tuple[UUID, ...]:
    result: list[UUID] = []
    for ordinal, item in enumerate(command.requirements, start=1):
        requirement_id = cast(
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
        result.append(requirement_id)
    return tuple(result)


def _booking_policy(command: CreateOfferingCommand) -> dict[str, object]:
    policy = command.reservation_policy
    channels = policy.channel_policy
    channel_policy: dict[str, object] = {}
    if channels is not None:
        channel_policy = {
            "channels": list(channels.channels),
            "reconcile_after_seconds": channels.reconcile_after_seconds,
            "retry_after_seconds": channels.retry_after_seconds,
        }
        if channels.provider_key is not None:
            channel_policy["provider_key"] = channels.provider_key.strip()
    return {
        "slot_step_minutes": command.slot_step_minutes,
        "attendance": {
            "confirmation_required": policy.attendance_confirmation_required,
            "attendance_request_before_minutes": policy.attendance_request_before_minutes,
            "decline_action": policy.decline_action,
            "no_response_action": "keep",
            "no_show_after_minutes": policy.no_show_after_minutes,
        },
        "communications": {
            "confirmation": policy.confirmation,
            "reminders_before_minutes": list(policy.reminders_before_minutes),
            "channel_policy": channel_policy,
        },
        "slot_recovery": {
            "enabled": policy.slot_recovery_enabled,
            "minimum_lead_minutes": policy.slot_recovery_minimum_lead_minutes,
        },
    }


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
