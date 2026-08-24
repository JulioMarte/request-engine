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
class DeactivateResourcePublicProfileCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    resource_id: UUID
    expected_revision: int
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ResourcePublicProfileState:
    resource_id: UUID
    resource_key: str
    display_name: str
    role_label: str | None
    profile_image_ref: str | None
    active: bool
    revision: int


class ResourcePublicProfileHandler(Protocol):
    async def set_public_profile(
        self, command: SetResourcePublicProfileCommand
    ) -> ResourcePublicProfileState: ...

    async def deactivate_public_profile(
        self, command: DeactivateResourcePublicProfileCommand
    ) -> ResourcePublicProfileState: ...


async def set_resource_public_profile(
    handler: ResourcePublicProfileHandler,
    command: SetResourcePublicProfileCommand,
) -> ResourcePublicProfileState:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if not command.display_name.strip():
        raise ValueError("display_name is required")
    if command.expected_revision is not None and command.expected_revision < 1:
        raise ValueError("expected_revision must be positive")
    return await handler.set_public_profile(command)


async def deactivate_resource_public_profile(
    handler: ResourcePublicProfileHandler,
    command: DeactivateResourcePublicProfileCommand,
) -> ResourcePublicProfileState:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if command.expected_revision < 1:
        raise ValueError("expected_revision must be positive")
    return await handler.deactivate_public_profile(command)
