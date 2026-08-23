from typing import Literal, Protocol

from request_engine.modules.booking.contracts.discovery import PublishedSlotReader


class RemotePublishedSlotReader(PublishedSlotReader, Protocol):
    """Published-slot port whose implementation crosses a process boundary."""

    @property
    def trust_boundary(self) -> Literal["remote"]: ...
