from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

PublicContactChannel = Literal["phone", "whatsapp", "email"]


@dataclass(frozen=True, slots=True)
class OrganizationPublicContactInput:
    channel: PublicContactChannel
    normalized_value: str
    label: str | None = None


@dataclass(frozen=True, slots=True)
class OrganizationPublicContactsState:
    organization_id: UUID
    contacts: tuple[OrganizationPublicContactInput, ...]


@dataclass(frozen=True, slots=True)
class SetOrganizationPublicContactsCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    contacts: tuple[OrganizationPublicContactInput, ...]
    idempotency_key: str


class SetOrganizationPublicContactsHandler(Protocol):
    async def set_organization_public_contacts(
        self, command: SetOrganizationPublicContactsCommand
    ) -> OrganizationPublicContactsState: ...


async def set_organization_public_contacts(
    handler: SetOrganizationPublicContactsHandler,
    command: SetOrganizationPublicContactsCommand,
) -> OrganizationPublicContactsState:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    seen: set[tuple[str, str]] = set()
    for contact in command.contacts:
        if contact.channel not in {"phone", "whatsapp", "email"}:
            raise ValueError("unsupported public contact channel")
        if not contact.normalized_value.strip():
            raise ValueError("normalized_value is required")
        key = (contact.channel, contact.normalized_value)
        if key in seen:
            raise ValueError("duplicate public contact")
        seen.add(key)
        if contact.label is not None and not contact.label.strip():
            raise ValueError("label cannot be blank")
    return await handler.set_organization_public_contacts(command)
