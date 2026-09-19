from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from request_engine.platform.security.authentication import (
    AuthenticatedSubject,
    AuthenticatedSubjectClass,
)


class WorkloadAuthenticationError(RuntimeError):
    pass


class WorkloadCredentialInvalid(WorkloadAuthenticationError):
    pass


class WorkloadKind(StrEnum):
    AGENT = "agent"
    INTEGRATION = "integration"
    SYSTEM = "system"


class WorkloadIdentityStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class WorkloadCredentialStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class WorkloadAuthorityStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class WorkloadCredentialEvidence:
    raw_token: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ParsedWorkloadToken:
    credential_id: UUID
    secret: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class WorkloadCredentialSnapshot:
    credential_id: UUID
    workload_identity_id: UUID
    identity_authority_id: UUID
    workload_kind: WorkloadKind
    token_digest: bytes = field(repr=False)
    credential_status: WorkloadCredentialStatus
    identity_status: WorkloadIdentityStatus
    authority_status: WorkloadAuthorityStatus
    expires_at: datetime


class WorkloadCredentialReader(Protocol):
    async def read_workload_credential(
        self, *, credential_id: UUID
    ) -> WorkloadCredentialSnapshot | None: ...


class WorkloadCredentialAuthenticator:
    """Verify a first-party workload bearer and emit identity only."""

    def __init__(self, reader: WorkloadCredentialReader) -> None:
        self._reader = reader

    async def authenticate(self, evidence: WorkloadCredentialEvidence) -> AuthenticatedSubject:
        parsed = parse_workload_token(evidence.raw_token)
        snapshot = await self._reader.read_workload_credential(credential_id=parsed.credential_id)
        if snapshot is None or not _snapshot_is_usable(snapshot):
            raise WorkloadCredentialInvalid("workload credential is invalid")
        actual = hashlib.sha256(parsed.secret.encode("utf-8")).digest()
        if not hmac.compare_digest(actual, snapshot.token_digest):
            raise WorkloadCredentialInvalid("workload credential is invalid")
        return AuthenticatedSubject(
            authority_id=str(snapshot.identity_authority_id),
            subject_id=str(snapshot.workload_identity_id),
            subject_class=AuthenticatedSubjectClass.WORKLOAD,
            metadata={
                "authentication_authority_kind": "workload",
                "workload_kind": snapshot.workload_kind.value,
            },
        )


def parse_workload_token(raw_token: str) -> ParsedWorkloadToken:
    try:
        token_id_value, secret = raw_token.split(".", maxsplit=1)
        credential_id = UUID(token_id_value)
    except (AttributeError, ValueError) as exc:
        raise WorkloadCredentialInvalid("workload credential is malformed") from exc
    if not secret or len(secret) > 256:
        raise WorkloadCredentialInvalid("workload credential is malformed")
    return ParsedWorkloadToken(credential_id=credential_id, secret=secret)


def _snapshot_is_usable(snapshot: WorkloadCredentialSnapshot) -> bool:
    return (
        snapshot.credential_status is WorkloadCredentialStatus.ACTIVE
        and snapshot.identity_status is WorkloadIdentityStatus.ACTIVE
        and snapshot.authority_status is WorkloadAuthorityStatus.ACTIVE
        and snapshot.expires_at > datetime.now(UTC)
        and len(snapshot.token_digest) == hashlib.sha256().digest_size
    )
