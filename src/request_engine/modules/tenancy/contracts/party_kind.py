"""Canonical Party subject kinds shared by registry and identity exchange."""

from enum import StrEnum


class PartyKind(StrEnum):
    """Stable V3 Party kinds; organization represents a legal/business entity."""

    PERSON = "person"
    ORGANIZATION = "organization"
