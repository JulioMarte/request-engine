from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

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
    seen: set[tuple[str, str]] = set()
    for contact in command.contacts:
        if contact.channel not in ("phone", "whatsapp", "email"):
            raise ValueError("unsupported public contact channel")
        if not contact.normalized_value.strip():
            raise ValueError("normalized_value is required")
        if contact.label is not None and not contact.label.strip():
            raise ValueError("label cannot be blank")
        key = (contact.channel, contact.normalized_value)
        if key in seen:
            raise ValueError("duplicate public contact endpoint")
        seen.add(key)
    return await handler.set_location_public_contacts(command)
