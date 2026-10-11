from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ChannelConfigurationQuery:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    purpose: str


@dataclass(frozen=True, slots=True)
class ChannelConfiguration:
    purpose: str
    configured: bool
    revision: int
    enabled: bool | None
    channel_policy: dict[str, object] | None


class ChannelConfigurationReader(Protocol):
    async def read_configuration(
        self, query: ChannelConfigurationQuery
    ) -> ChannelConfiguration: ...
