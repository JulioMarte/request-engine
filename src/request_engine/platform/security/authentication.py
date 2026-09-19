from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol


def _empty_metadata() -> dict[str, str]:
    return {}


class AuthenticatedSubjectClass(StrEnum):
    """Authentication-side subject class before RE Principal resolution."""

    HUMAN = "human"
    WORKLOAD = "workload"


@dataclass(frozen=True, slots=True)
class AuthenticatedSubject:
    """Provider-neutral identity assertion produced after credential verification.

    This object deliberately carries no Organization, Principal id, capability,
    Representation, delegation, or provider role. Those are Request Engine-owned
    authorization facts resolved only after authentication succeeds.
    """

    authority_id: str
    subject_id: str
    subject_class: AuthenticatedSubjectClass
    metadata: Mapping[str, str] = field(default_factory=_empty_metadata)

    def __post_init__(self) -> None:
        if not self.authority_id.strip():
            raise ValueError("authority_id is required")
        if not self.subject_id.strip():
            raise ValueError("subject_id is required")


class AuthenticationEvidence(Protocol):
    """Opaque deployment/provider-specific credential evidence."""


class Authenticator(Protocol):
    """Narrow provider-neutral facet that only establishes authenticated identity."""

    async def authenticate(self, evidence: AuthenticationEvidence) -> AuthenticatedSubject: ...
