from typing import Protocol
from uuid import UUID


class ReadSnapshot(Protocol):
    """Opaque handle for one coherent tenant-scoped read snapshot."""

    @property
    def organization_id(self) -> UUID: ...
