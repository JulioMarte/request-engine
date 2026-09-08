from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from request_engine.platform.security.native_auth import (
    CredentialInvalid,
    digest_opaque_secret,
    parse_opaque_token,
    verify_password,
)
from request_engine.platform.security.native_human_auth import (
    NativeHumanAuthService,
    NativeIdentityAlreadyExists,
    NativePasswordCredentialSnapshot,
    RecoveryIntentInvalid,
)
from request_engine.platform.security.native_session import (
    NativeCredentialStatus,
    NativeIdentityStatus,
)

pytestmark = [pytest.mark.unit, pytest.mark.security]
NOW = datetime(2026, 9, 8, tzinfo=timezone.utc)
PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "new correct horse battery staple"


class FakeNativeHumanAuthStore:
    def __init__(self, snapshot: NativePasswordCredentialSnapshot | None = None) -> None:
        self.snapshot = snapshot
        self.identity_created = True
        self.session_created = True
        self.recovery_created = True
        self.recovery_result: UUID | None = None
        self.created_identity: dict[str, object] | None = None
        self.created_session: dict[str, object] | None = None
        self.created_recovery: dict[str, object] | None = None
        self.consumed_recovery: dict[str, object] | None = None
        self.rotated_password: dict[str, object] | None = None

    async def read_password_credential(
        self, *, identity_authority_id: UUID, login_handle: str
    ) -> NativePasswordCredentialSnapshot | None:
        return self.snapshot

    async def create_identity(self, **kwargs: object) -> bool:
        self.created_identity = kwargs
        return self.identity_created

    async def create_session(self, **kwargs: object) -> bool:
        self.created_session = kwargs
        return self.session_created

    async def revoke_session(self, **kwargs: object) -> bool:
        return True

    async def revoke_all_sessions(self, **kwargs: object) -> bool:
        return True

    async def rotate_password(self, **kwargs: object) -> bool:
        self.rotated_password = kwargs
        return True

    async def disable_identity(self, **kwargs: object) -> bool:
        return True

    async def create_recovery_intent(self, **kwargs: object) -> bool:
        self.created_recovery = kwargs
        return self.recovery_created

    async def consume_recovery_intent(self, **kwargs: object) -> UUID | None:
        self.consumed_recovery = kwargs
        return self.recovery_result


def _snapshot() -> NativePasswordCredentialSnapshot:
    from request_engine.platform.security.native_auth import hash_password

    return NativePasswordCredentialSnapshot(
        native_identity_id=uuid4(),
        credential_id=uuid4(),
        verifier=hash_password(PASSWORD),
        identity_status=NativeIdentityStatus.ACTIVE,
        credential_status=NativeCredentialStatus.ACTIVE,
        session_epoch=1,
        identity_revision=1,
        credential_revision=1,
    )


@pytest.mark.asyncio
async def test_enrollment_normalizes_handle_and_persists_only_verifier() -> None:
    store = FakeNativeHumanAuthStore()
    service = NativeHumanAuthService(store=store, clock=lambda: NOW)

    enrollment = await service.enroll_password_identity(
        identity_authority_id=uuid4(),
        login_handle="  Julio@Example.COM ",
        password=PASSWORD,
    )

    assert enrollment.login_handle == "julio@example.com"
    assert store.created_identity is not None
    verifier = str(store.created_identity["verifier"])
    assert PASSWORD not in verifier
    assert verify_password(PASSWORD, verifier)


@pytest.mark.asyncio
async def test_duplicate_enrollment_has_typed_failure() -> None:
    store = FakeNativeHumanAuthStore()
    store.identity_created = False
    service = NativeHumanAuthService(store=store, clock=lambda: NOW)

    with pytest.raises(NativeIdentityAlreadyExists):
        await service.enroll_password_identity(
            identity_authority_id=uuid4(), login_handle="j@example.com", password=PASSWORD
        )


@pytest.mark.asyncio
async def test_login_keeps_raw_session_token_out_of_store_boundary() -> None:
    snapshot = _snapshot()
    store = FakeNativeHumanAuthStore(snapshot)
    service = NativeHumanAuthService(store=store, clock=lambda: NOW)

    issued = await service.authenticate_password(
        identity_authority_id=uuid4(), login_handle="j@example.com", password=PASSWORD
    )

    assert store.created_session is not None
    parsed = parse_opaque_token(issued.raw_token)
    assert parsed.token_id == issued.session_id
    assert store.created_session["session_id"] == issued.session_id
    assert store.created_session["token_digest"] == digest_opaque_secret(parsed.secret)
    assert issued.raw_token not in repr(store.created_session)
    assert PASSWORD not in repr(store.created_session)


@pytest.mark.asyncio
async def test_wrong_password_never_creates_session() -> None:
    store = FakeNativeHumanAuthStore(_snapshot())
    service = NativeHumanAuthService(store=store, clock=lambda: NOW)

    with pytest.raises(CredentialInvalid):
        await service.authenticate_password(
            identity_authority_id=uuid4(),
            login_handle="j@example.com",
            password="definitely the wrong password",
        )

    assert store.created_session is None


@pytest.mark.asyncio
async def test_login_loses_cleanly_to_concurrent_credential_revocation() -> None:
    store = FakeNativeHumanAuthStore(_snapshot())
    store.session_created = False
    service = NativeHumanAuthService(store=store, clock=lambda: NOW)

    with pytest.raises(CredentialInvalid):
        await service.authenticate_password(
            identity_authority_id=uuid4(), login_handle="j@example.com", password=PASSWORD
        )


@pytest.mark.asyncio
async def test_password_rotation_persists_new_verifier_not_raw_password() -> None:
    snapshot = _snapshot()
    store = FakeNativeHumanAuthStore(snapshot)
    service = NativeHumanAuthService(store=store, clock=lambda: NOW)

    await service.rotate_password(
        identity_authority_id=uuid4(),
        login_handle="j@example.com",
        current_password=PASSWORD,
        new_password=NEW_PASSWORD,
    )

    assert store.rotated_password is not None
    assert store.rotated_password["expected_credential_id"] == snapshot.credential_id
    verifier = str(store.rotated_password["new_verifier"])
    assert NEW_PASSWORD not in verifier
    assert verify_password(NEW_PASSWORD, verifier)


@pytest.mark.asyncio
async def test_unknown_recovery_request_does_not_create_token() -> None:
    store = FakeNativeHumanAuthStore(None)
    service = NativeHumanAuthService(store=store, clock=lambda: NOW)

    result = await service.issue_recovery(
        identity_authority_id=uuid4(), login_handle="missing@example.com"
    )

    assert result is None
    assert store.created_recovery is None


@pytest.mark.asyncio
async def test_recovery_raw_token_remains_above_store_boundary() -> None:
    snapshot = _snapshot()
    store = FakeNativeHumanAuthStore(snapshot)
    service = NativeHumanAuthService(store=store, clock=lambda: NOW)

    recovery = await service.issue_recovery(
        identity_authority_id=uuid4(), login_handle="j@example.com"
    )

    assert recovery is not None
    assert store.created_recovery is not None
    parsed = parse_opaque_token(recovery.raw_token)
    assert store.created_recovery["recovery_id"] == recovery.recovery_id
    assert store.created_recovery["token_digest"] == digest_opaque_secret(parsed.secret)
    assert recovery.raw_token not in repr(store.created_recovery)


@pytest.mark.asyncio
async def test_consumed_or_invalid_recovery_has_typed_failure() -> None:
    store = FakeNativeHumanAuthStore(_snapshot())
    service = NativeHumanAuthService(store=store, clock=lambda: NOW)
    from request_engine.platform.security.native_auth import issue_opaque_token

    token = issue_opaque_token()
    with pytest.raises(RecoveryIntentInvalid):
        await service.consume_recovery(raw_token=token.raw_token, new_password=NEW_PASSWORD)

    assert store.consumed_recovery is not None
    assert token.raw_token not in repr(store.consumed_recovery)
