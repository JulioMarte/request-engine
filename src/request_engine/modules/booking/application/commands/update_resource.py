"""Rename a Resource (``booking_resource_update``).

The internal label is not availability-material: the command compares the
caller's ``expected_resource_availability_revision`` as a precondition and never
advances it. Discovery's public profile (``resource_public_profiles``) is a
separate owner fact and is not changed here.
"""

import re
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

MAX_RESOURCE_DISPLAY_NAME = 200
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True, slots=True)
class UpdateResourceCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    resource_id: UUID
    display_name: str
    expected_resource_availability_revision: int
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ResourceUpdateState:
    resource_id: UUID
    resource_key: str
    display_name: str
    active: bool
    availability_revision: int


class UpdateResourceHandler(Protocol):
    async def update_resource(self, command: UpdateResourceCommand) -> ResourceUpdateState: ...


def normalize_resource_display_name(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("display_name is required")
    if len(cleaned) > MAX_RESOURCE_DISPLAY_NAME:
        raise ValueError(f"display_name must be at most {MAX_RESOURCE_DISPLAY_NAME} characters")
    if _CONTROL.search(cleaned):
        raise ValueError("display_name must not contain control characters")
    return cleaned


async def update_resource(
    handler: UpdateResourceHandler, command: UpdateResourceCommand
) -> ResourceUpdateState:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if command.expected_resource_availability_revision <= 0:
        raise ValueError("expected_resource_availability_revision must be positive")
    normalize_resource_display_name(command.display_name)
    return await handler.update_resource(command)
