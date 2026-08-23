from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.discovery.application.commands.public_profile import (
    ResourcePublicProfileState,
    SetResourcePublicProfileCommand,
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


def _json(state: ResourcePublicProfileState) -> dict[str, object]:
    return {
        "resource_id": str(state.resource_id),
        "resource_key": state.resource_key,
        "display_name": state.display_name,
        "role_label": state.role_label,
        "profile_image_ref": state.profile_image_ref,
        "revision": state.revision,
    }


def _state(value: dict[str, object]) -> ResourcePublicProfileState:
    return ResourcePublicProfileState(
        resource_id=UUID(cast(str, value["resource_id"])),
        resource_key=cast(str, value["resource_key"]),
        display_name=cast(str, value["display_name"]),
        role_label=cast(str | None, value["role_label"]),
        profile_image_ref=cast(str | None, value["profile_image_ref"]),
        revision=cast(int, value["revision"]),
    )


class PostgresResourcePublicProfileCommands:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def set_public_profile(
        self, command: SetResourcePublicProfileCommand
    ) -> ResourcePublicProfileState:
        fingerprint = command_fingerprint(
            "discovery.set_resource_public_profile",
            {
                "authority_party_id": command.authority_party_id,
                "resource_id": command.resource_id,
                "display_name": command.display_name.strip(),
                "role_label": command.role_label,
                "profile_image_ref": command.profile_image_ref,
                "expected_revision": command.expected_revision,
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idem_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="discovery.set_resource_public_profile",
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _state(cast(dict[str, object], replay["state"]))
            authority = await require_operational_authority(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                authority_party_id=command.authority_party_id,
                scope_key=MANAGE_DISCOVERY_SCOPE,
            )
            resource = (
                await session.execute(
                    text(
                        "SELECT resource_key FROM request_engine.resources "
                        "WHERE organization_id=:org AND id=:resource FOR UPDATE"
                    ),
                    {"org": command.organization_id, "resource": command.resource_id},
                )
            ).mappings().first()
            if resource is None:
                raise DiscoveryConfigurationConflict("resource unavailable")
            current = (
                await session.execute(
                    text(
                        "SELECT revision FROM request_engine.resource_public_profiles "
                        "WHERE organization_id=:org AND resource_id=:resource FOR UPDATE"
                    ),
                    {"org": command.organization_id, "resource": command.resource_id},
                )
            ).mappings().first()
            row = await self._persist(session, command, current)
            state = ResourcePublicProfileState(
                resource_id=command.resource_id,
                resource_key=cast(str, resource["resource_key"]),
                display_name=cast(str, row["display_name"]),
                role_label=cast(str | None, row["role_label"]),
                profile_image_ref=cast(str | None, row["profile_image_ref"]),
                revision=cast(int, row["revision"]),
            )
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name="discovery.set_resource_public_profile",
                aggregate_kind="ResourcePublicProfile",
                aggregate_id=command.resource_id,
                idempotency_id=idem_id,
                details={"authority": authority.audit_details()},
            )
            await complete_idempotency(session, idem_id, {"state": _json(state)})
            return state

    async def _persist(
        self,
        session: AsyncSession,
        command: SetResourcePublicProfileCommand,
        current: RowMapping | None,
    ) -> RowMapping:
        values: dict[str, object] = {
            "org": command.organization_id,
            "resource": command.resource_id,
            "display": command.display_name.strip(),
            "role": command.role_label.strip() if command.role_label else None,
            "image": command.profile_image_ref.strip() if command.profile_image_ref else None,
        }
        if current is None:
            if command.expected_revision is not None:
                raise DiscoveryConfigurationConflict("public profile does not yet exist")
            return (
                await session.execute(
                    text(
                        "INSERT INTO request_engine.resource_public_profiles "
                        "(organization_id,resource_id,display_name,role_label,profile_image_ref) "
                        "VALUES (:org,:resource,:display,:role,:image) "
                        "RETURNING display_name,role_label,profile_image_ref,revision"
                    ),
                    values,
                )
            ).mappings().one()
        actual = cast(int, current["revision"])
        if command.expected_revision != actual:
            raise DiscoveryRevisionConflict(command.resource_id, command.expected_revision or 0, actual)
        values["expected"] = actual
        return (
            await session.execute(
                text(
                    "UPDATE request_engine.resource_public_profiles SET "
                    "display_name=:display,role_label=:role,profile_image_ref=:image,active=true,"
                    "revision=revision+1 WHERE organization_id=:org AND resource_id=:resource "
                    "AND revision=:expected RETURNING display_name,role_label,profile_image_ref,revision"
                ),
                values,
            )
        ).mappings().one()
