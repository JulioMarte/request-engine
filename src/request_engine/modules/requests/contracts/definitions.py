from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ResolvedRequestDefinitionVersion:
    id: UUID
    request_key: str
    version: int
