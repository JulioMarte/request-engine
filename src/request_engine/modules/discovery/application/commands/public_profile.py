from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class SetResourcePublicProfileCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    resource_id: UUID
    display_name: str
    role_label: str | None
    profile_image_ref: str | None
    idempotency_key: str
    expected_revision: int | None = None


@dataclass(frozen=True, slots=True)
class ResourcePublicProfileState:
    resource_id: UUID
    resource_key: str
    display_name: str
    role_label: str | None
    profile_image_ref: str | None
    revision: int


class SetResourcePublicProfileHandler(Protocol):
    async def set_public_profile(
        self, command: SetResourcePublicProfileCommand
    ) -> ResourcePublicProfileState: ...


async def set_resource_public_profile(
    handler: SetResourcePublicProfileHandler,
    command: SetResourcePublicProfileCommand,
) -> ResourcePublicProfileState:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if not command.display_name.strip():
        raise ValueError("display_name is required")
    if command.expected_revision is not None and command.expected_revision < 1:
        raise ValueError("expected_revision must be positive")
    return await handler.set_public_profile(command)
