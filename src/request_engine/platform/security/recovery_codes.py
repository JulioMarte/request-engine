"""Digest-only recovery code generation and lifecycle (ADR 0014 §5.7).

Codes are generated here as 128-bit base32 values and returned to the caller
exactly once. Only a SHA-256 digest is persisted, so the durable model can never
replay a code. Consumption is single-use and owner-resolving; promotion moves a
first-run setup-scoped set onto the permanent native identity.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

_RECOVERY_CODE_BYTES = 16
_DEFAULT_CODE_COUNT = 10
_MAX_CODE_COUNT = 50


class RecoveryCodeError(RuntimeError):
    """Base class for recovery-code lifecycle failures."""


class RecoveryCodeInvalid(RecoveryCodeError):
    pass


@dataclass(frozen=True, slots=True)
class RecoveryCodeSetSummary:
    set_id: UUID
    version: int
    status: str
    created_at: datetime
    total_codes: int
    remaining_codes: int


@dataclass(frozen=True, slots=True)
class RecoveryCodeConsumed:
    native_identity_id: UUID
    set_id: UUID
    code_id: UUID


class RecoveryCodeStore(Protocol):
    async def create_set(
        self,
        *,
        set_id: UUID,
        code_digests: Sequence[bytes],
        native_identity_id: UUID | None = None,
        setup_session_id: UUID | None = None,
    ) -> bool: ...

    async def consume(self, *, code_digest: bytes) -> RecoveryCodeConsumed | None: ...

    async def promote(self, *, set_id: UUID, native_identity_id: UUID) -> bool: ...

    async def revoke(self, *, set_id: UUID, reason: str) -> bool: ...

    async def summary(self, *, native_identity_id: UUID) -> tuple[RecoveryCodeSetSummary, ...]: ...


def generate_recovery_codes(count: int = _DEFAULT_CODE_COUNT) -> tuple[str, ...]:
    if count < 1 or count > _MAX_CODE_COUNT:
        raise ValueError("recovery code count must be between 1 and 50")
    return tuple(
        _group(
            base64.b32encode(secrets.token_bytes(_RECOVERY_CODE_BYTES)).decode("ascii").rstrip("=")
        )
        for _ in range(count)
    )


def normalize_recovery_code(code: str) -> str:
    return "".join(
        character
        for character in code.upper()
        if ("A" <= character <= "Z") or ("0" <= character <= "9")
    )


def recovery_code_digest(code: str) -> bytes:
    return hashlib.sha256(normalize_recovery_code(code).encode("ascii")).digest()


def _group(raw: str) -> str:
    return "-".join(raw[index : index + 4] for index in range(0, len(raw), 4))


class NativeRecoveryCodeService:
    """Generate, consume and rotate digest-only recovery code sets."""

    def __init__(
        self,
        *,
        store: RecoveryCodeStore,
        code_count: int = _DEFAULT_CODE_COUNT,
    ) -> None:
        if code_count < 1 or code_count > _MAX_CODE_COUNT:
            raise ValueError("recovery code count must be between 1 and 50")
        self._store = store
        self._code_count = code_count

    async def issue_for_identity(self, *, native_identity_id: UUID) -> tuple[str, ...]:
        return await self._issue(native_identity_id=native_identity_id)

    async def issue_for_setup_session(self, *, setup_session_id: UUID) -> tuple[str, ...]:
        return await self._issue(setup_session_id=setup_session_id)

    async def consume(self, *, code: str) -> RecoveryCodeConsumed | None:
        digest = recovery_code_digest(code)
        if len(normalize_recovery_code(code)) < 16:
            return None
        return await self._store.consume(code_digest=digest)

    async def promote(self, *, set_id: UUID, native_identity_id: UUID) -> bool:
        return await self._store.promote(set_id=set_id, native_identity_id=native_identity_id)

    async def revoke(self, *, set_id: UUID, reason: str) -> bool:
        normalized = reason.strip()
        if not normalized or len(normalized) > 200:
            raise ValueError("revocation reason must contain between 1 and 200 characters")
        return await self._store.revoke(set_id=set_id, reason=normalized)

    async def summary(self, *, native_identity_id: UUID) -> tuple[RecoveryCodeSetSummary, ...]:
        return await self._store.summary(native_identity_id=native_identity_id)

    async def _issue(
        self,
        *,
        native_identity_id: UUID | None = None,
        setup_session_id: UUID | None = None,
    ) -> tuple[str, ...]:
        codes = generate_recovery_codes(self._code_count)
        created = await self._store.create_set(
            set_id=uuid4(),
            code_digests=tuple(recovery_code_digest(code) for code in codes),
            native_identity_id=native_identity_id,
            setup_session_id=setup_session_id,
        )
        if not created:
            raise RecoveryCodeInvalid("recovery code set could not be created")
        return codes
