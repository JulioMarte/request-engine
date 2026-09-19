from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest

from request_engine.platform.security.recovery_codes import (
    NativeRecoveryCodeService,
    RecoveryCodeConsumed,
    RecoveryCodeSetSummary,
    generate_recovery_codes,
    normalize_recovery_code,
    recovery_code_digest,
)

pytestmark = [pytest.mark.unit, pytest.mark.security]


@dataclass
class CreatedSet:
    set_id: UUID
    code_digests: tuple[bytes, ...]
    native_identity_id: UUID | None
    setup_session_id: UUID | None


class FakeRecoveryCodeStore:
    def __init__(self, *, created: bool = True) -> None:
        self._created = created
        self.created: list[CreatedSet] = []
        self.consumed: list[bytes] = []
        self.promoted: list[tuple[UUID, UUID]] = []
        self.revoked: list[tuple[UUID, str]] = []

    async def create_set(
        self,
        *,
        set_id: UUID,
        code_digests: Sequence[bytes],
        native_identity_id: UUID | None = None,
        setup_session_id: UUID | None = None,
    ) -> bool:
        self.created.append(
            CreatedSet(
                set_id=set_id,
                code_digests=tuple(code_digests),
                native_identity_id=native_identity_id,
                setup_session_id=setup_session_id,
            )
        )
        return self._created

    async def consume(self, *, code_digest: bytes) -> RecoveryCodeConsumed | None:
        self.consumed.append(code_digest)
        return RecoveryCodeConsumed(native_identity_id=uuid4(), set_id=uuid4(), code_id=uuid4())

    async def promote(self, *, set_id: UUID, native_identity_id: UUID) -> bool:
        self.promoted.append((set_id, native_identity_id))
        return True

    async def revoke(self, *, set_id: UUID, reason: str) -> bool:
        self.revoked.append((set_id, reason))
        return True

    async def summary(self, *, native_identity_id: UUID) -> tuple[RecoveryCodeSetSummary, ...]:
        return ()


def test_generated_codes_are_grouped_base32() -> None:
    codes = generate_recovery_codes(3)
    assert len(codes) == 3
    for code in codes:
        assert len(code) == 26 + 6  # 26 base32 chars in 4-char groups
        assert all(character.isalnum() or character == "-" for character in code)
    assert len(set(codes)) == 3


def test_digest_is_stable_across_normalization() -> None:
    code = generate_recovery_codes(1)[0]
    variants = [code, code.lower(), code.replace("-", ""), f"  {code}  "]
    digests = {recovery_code_digest(variant) for variant in variants}
    assert len(digests) == 1
    assert len(digests.pop()) == 32
    assert normalize_recovery_code(code).isalnum()


@pytest.mark.asyncio
async def test_issue_returns_plaintext_once_and_persists_only_digests() -> None:
    store = FakeRecoveryCodeStore()
    service = NativeRecoveryCodeService(store=store, code_count=5)
    identity_id = uuid4()

    codes = await service.issue_for_identity(native_identity_id=identity_id)

    assert len(codes) == 5
    assert len(store.created) == 1
    recorded = store.created[0]
    assert recorded.native_identity_id == identity_id
    assert recorded.setup_session_id is None
    assert len(recorded.code_digests) == 5
    assert all(len(digest) == 32 for digest in recorded.code_digests)
    # No plaintext code can appear in the persisted digests.
    assert all(code.encode("ascii") not in recorded.code_digests for code in codes)


@pytest.mark.asyncio
async def test_consume_normalizes_before_lookup() -> None:
    store = FakeRecoveryCodeStore()
    service = NativeRecoveryCodeService(store=store)
    code = generate_recovery_codes(1)[0]

    consumed = await service.consume(code=code.lower().replace("-", " "))

    assert consumed is not None
    assert store.consumed == [recovery_code_digest(code)]


@pytest.mark.asyncio
async def test_consume_rejects_short_input_without_store_call() -> None:
    store = FakeRecoveryCodeStore()
    service = NativeRecoveryCodeService(store=store)

    assert await service.consume(code="abcd") is None
    assert store.consumed == []


def test_generate_rejects_invalid_count() -> None:
    with pytest.raises(ValueError):
        generate_recovery_codes(0)
    with pytest.raises(ValueError):
        generate_recovery_codes(51)
