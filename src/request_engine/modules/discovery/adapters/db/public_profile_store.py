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


def state_to_json(state: ResourcePublicProfileState) -> dict[str, object]:
    return {
        "resource_id": str(state.resource_id),
        "resource_key": state.resource_key,
        "display_name": state.display_name,
        "role_label": state.role_label,
        "profile_image_ref": state.profile_image_ref,
        "revision": state.revision,
    }


def state_from_json(value: dict[str, object]) -> ResourcePublicProfileState:
    return ResourcePublicProfileState(
        resource_id=UUID(cast(str, value["resource_id"])),
        resource_key=cast(str, value["resource_key"]),
        display_name=cast(str, value["display_name"]),
        role_label=cast(str | None, value["role_label"]),
        profile_image_ref=cast(str | None, value["profile_image_ref"]),
        revision=cast(int, value["revision"]),
    )


async def lock_resource(
    session: AsyncSession, command: SetResourcePublicProfileCommand
) -> str:
    row = (
        await session.execute(
            text(
                "SELECT resource_key FROM request_engine.resources "
                "WHERE organization_id=:org AND id=:resource FOR UPDATE"
            ),
            {"org": command.organization_id, "resource": command.resource_id},
        )
    ).mappings().first()
    if row is None:
        raise DiscoveryConfigurationConflict("resource unavailable")
    return cast(str, row["resource_key"])


async def upsert_profile(
    session: AsyncSession, command: SetResourcePublicProfileCommand
) -> RowMapping:
    current = (
        await session.execute(
            text(
                "SELECT revision FROM request_engine.resource_public_profiles "
                "WHERE organization_id=:org AND resource_id=:resource FOR UPDATE"
            ),
            {"org": command.organization_id, "resource": command.resource_id},
        )
    ).mappings().first()
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
                "AND revision=:expected RETURNING display_name,role_label,"
                "profile_image_ref,revision"
            ),
            values,
        )
    ).mappings().one()
