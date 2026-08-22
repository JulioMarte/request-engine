from dataclasses import dataclass, replace
from typing import Literal, Protocol
from uuid import UUID

from request_engine.platform.public_contacts import (
    PublicContactValidationError,
    normalize_public_contact_value,
)

PublicContactChannel = Literal["phone", "whatsapp", "email"]


@dataclass(frozen=True, slots=True)
class LocationPublicContactInput:
    channel: PublicContactChannel
    normalized_value: str
    label: str | None = None


@dataclass(frozen=True, slots=True)
class LocationPublicContactsState:
    location_id: UUID
    contacts: tuple[LocationPublicContactInput, ...]


@dataclass(frozen=True, slots=True)
class SetLocationPublicContactsCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    location_id: UUID
    contacts: tuple[LocationPublicContactInput, ...]
    idempotency_key: str


class SetLocationPublicContactsHandler(Protocol):
    async def set_location_public_contacts(
        self, command: SetLocationPublicContactsCommand
    ) -> LocationPublicContactsState: ...


async def set_location_public_contacts(
    handler: SetLocationPublicContactsHandler,
    command: SetLocationPublicContactsCommand,
) -> LocationPublicContactsState:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    contacts: list[LocationPublicContactInput] = []
    seen: set[tuple[str, str]] = set()
    for contact in command.contacts:
        normalized = normalize_public_contact_value(
            contact.channel,
            contact.normalized_value,
        )
        if contact.label is not None and not contact.label.strip():
            raise PublicContactValidationError("label cannot be blank")
        key = (contact.channel, normalized)
        if key in seen:
            raise PublicContactValidationError("duplicate public contact endpoint")
        seen.add(key)
        contacts.append(replace(contact, normalized_value=normalized))
    normalized_command = replace(command, contacts=tuple(contacts))
    return await handler.set_location_public_contacts(normalized_command)
