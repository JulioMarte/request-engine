from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from request_engine.platform.security.assurance import AuthenticationAssurance
from request_engine.platform.security.native_auth import CredentialInvalid, issue_opaque_token
from request_engine.platform.security.native_session import (
    NativeCredentialRevoked,
    NativeCredentialStatus,
    NativeIdentityAuthorityStatus,
    NativeIdentityDisabled,
    NativeIdentityStatus,
    NativeSessionAuthenticator,
    NativeSessionEvidence,
    NativeSessionSnapshot,
    NativeSessionStatus,
    SessionExpired,
    SessionRevoked,
)

pytestmark = [pytest.mark.unit, pytest.mark.security]

NOW = datetime(2026, 9, 8, tzinfo=UTC)


class FakeSessionReader:
    def __init__(self, session: NativeSessionSnapshot | None) -> None:
        self.session = session

    async def read_native_session(self, *, session_id: UUID) -> NativeSessionSnapshot | None:
        if self.session is None or self.session.session_id != session_id:
            return None
        return self.session


class FakeSessionToucher:
    def __init__(self, *, raises: bool = False) -> None:
        self.calls: list[tuple[UUID, int]] = []
        self._raises = raises

    async def touch_native_session(self, *, session_id: UUID, min_interval_seconds: int) -> bool:
        self.calls.append((session_id, min_interval_seconds))
        if self._raises:
            raise RuntimeError("activity recording is unavailable")
        return True


def _snapshot(
    *,
    token_digest: bytes,
    session_id: UUID,
    session_epoch: int = 3,
    current_session_epoch: int = 3,
    session_status: NativeSessionStatus = NativeSessionStatus.ACTIVE,
    identity_status: NativeIdentityStatus = NativeIdentityStatus.ACTIVE,
    credential_status: NativeCredentialStatus | None = NativeCredentialStatus.ACTIVE,
    webauthn_credential_status: NativeCredentialStatus | None = None,
    expires_at: datetime = NOW + timedelta(hours=1),
    last_seen_at: datetime | None = None,
    authentication_assurance: AuthenticationAssurance = AuthenticationAssurance.SINGLE_FACTOR,
    user_verified: bool = False,
    recovery_derived: bool = False,
) -> NativeSessionSnapshot:
    return NativeSessionSnapshot(
        session_id=session_id,
        native_identity_id=uuid4(),
        identity_authority_id=uuid4(),
        password_credential_id=uuid4(),
        password_credential_status=credential_status,
        webauthn_credential_id=None,
        webauthn_credential_status=webauthn_credential_status,
        token_digest=token_digest,
        session_epoch=session_epoch,
        current_session_epoch=current_session_epoch,
        session_status=session_status,
        identity_status=identity_status,
        authority_status=NativeIdentityAuthorityStatus.ACTIVE,
        authentication_methods=("password",),
        authentication_assurance=authentication_assurance,
        user_verified=user_verified,
        recovery_derived=recovery_derived,
        expires_at=expires_at,
        created_at=NOW,
        last_seen_at=last_seen_at,
        authenticated_at=NOW,
    )


def _webauthn_snapshot(
    *,
    token_digest: bytes,
    session_id: UUID,
    webauthn_credential_status: NativeCredentialStatus | None = NativeCredentialStatus.ACTIVE,
    authentication_assurance: AuthenticationAssurance = AuthenticationAssurance.PHISHING_RESISTANT,
    user_verified: bool = True,
) -> NativeSessionSnapshot:
    return NativeSessionSnapshot(
        session_id=session_id,
        native_identity_id=uuid4(),
        identity_authority_id=uuid4(),
        password_credential_id=None,
        password_credential_status=None,
        webauthn_credential_id=uuid4(),
        webauthn_credential_status=webauthn_credential_status,
        token_digest=token_digest,
        session_epoch=1,
        current_session_epoch=1,
        session_status=NativeSessionStatus.ACTIVE,
        identity_status=NativeIdentityStatus.ACTIVE,
        authority_status=NativeIdentityAuthorityStatus.ACTIVE,
        authentication_methods=("webauthn",),
        authentication_assurance=authentication_assurance,
        user_verified=user_verified,
        recovery_derived=False,
        expires_at=NOW + timedelta(hours=1),
        created_at=NOW,
        last_seen_at=None,
        authenticated_at=NOW,
    )


@pytest.mark.asyncio
async def test_valid_session_authenticates_only_identity_not_authority() -> None:
    material = issue_opaque_token()
    session = _snapshot(token_digest=material.digest, session_id=material.token_id)
    authenticator = NativeSessionAuthenticator(
        session_reader=FakeSessionReader(session),
        clock=lambda: NOW,
    )

    subject = await authenticator.authenticate(NativeSessionEvidence(material.raw_token))

    assert subject.subject_id == str(session.native_identity_id)
    assert subject.authority_id == str(session.identity_authority_id)
    assert "capabilities" not in subject.metadata


@pytest.mark.asyncio
async def test_wrong_secret_fails_as_invalid_credential() -> None:
    material = issue_opaque_token()
    other = issue_opaque_token(token_id=material.token_id)
    session = _snapshot(token_digest=material.digest, session_id=material.token_id)
    authenticator = NativeSessionAuthenticator(
        session_reader=FakeSessionReader(session),
        clock=lambda: NOW,
    )

    with pytest.raises(CredentialInvalid):
        await authenticator.authenticate(NativeSessionEvidence(other.raw_token))


@pytest.mark.asyncio
async def test_session_epoch_change_invalidates_existing_session_immediately() -> None:
    material = issue_opaque_token()
    session = _snapshot(
        token_digest=material.digest,
        session_id=material.token_id,
        session_epoch=3,
        current_session_epoch=4,
    )
    authenticator = NativeSessionAuthenticator(
        session_reader=FakeSessionReader(session),
        clock=lambda: NOW,
    )

    with pytest.raises(SessionRevoked):
        await authenticator.authenticate(NativeSessionEvidence(material.raw_token))


@pytest.mark.asyncio
async def test_disabled_identity_invalidates_existing_session() -> None:
    material = issue_opaque_token()
    session = _snapshot(
        token_digest=material.digest,
        session_id=material.token_id,
        identity_status=NativeIdentityStatus.DISABLED,
    )
    authenticator = NativeSessionAuthenticator(
        session_reader=FakeSessionReader(session),
        clock=lambda: NOW,
    )

    with pytest.raises(NativeIdentityDisabled):
        await authenticator.authenticate(NativeSessionEvidence(material.raw_token))


@pytest.mark.asyncio
async def test_expired_session_fails_closed() -> None:
    material = issue_opaque_token()
    session = _snapshot(
        token_digest=material.digest,
        session_id=material.token_id,
        expires_at=NOW,
    )
    authenticator = NativeSessionAuthenticator(
        session_reader=FakeSessionReader(session),
        clock=lambda: NOW,
    )

    with pytest.raises(SessionExpired):
        await authenticator.authenticate(NativeSessionEvidence(material.raw_token))


@pytest.mark.asyncio
async def test_idle_timeout_rejects_a_stale_session_when_configured() -> None:
    material = issue_opaque_token()
    session = _snapshot(
        token_digest=material.digest,
        session_id=material.token_id,
        last_seen_at=NOW - timedelta(minutes=30),
    )
    authenticator = NativeSessionAuthenticator(
        session_reader=FakeSessionReader(session),
        idle_timeout=timedelta(minutes=15),
        clock=lambda: NOW,
    )

    with pytest.raises(SessionExpired):
        await authenticator.authenticate(NativeSessionEvidence(material.raw_token))


@pytest.mark.asyncio
async def test_idle_timeout_accepts_a_fresh_session_when_configured() -> None:
    material = issue_opaque_token()
    session = _snapshot(
        token_digest=material.digest,
        session_id=material.token_id,
        last_seen_at=NOW - timedelta(minutes=1),
    )
    authenticator = NativeSessionAuthenticator(
        session_reader=FakeSessionReader(session),
        idle_timeout=timedelta(minutes=15),
        clock=lambda: NOW,
    )

    subject = await authenticator.authenticate(NativeSessionEvidence(material.raw_token))

    assert subject.subject_id == str(session.native_identity_id)


@pytest.mark.asyncio
async def test_idle_timeout_defaults_to_disabled() -> None:
    material = issue_opaque_token()
    session = _snapshot(
        token_digest=material.digest,
        session_id=material.token_id,
        last_seen_at=NOW - timedelta(days=2),
    )
    authenticator = NativeSessionAuthenticator(
        session_reader=FakeSessionReader(session),
        clock=lambda: NOW,
    )

    subject = await authenticator.authenticate(NativeSessionEvidence(material.raw_token))

    assert subject.subject_id == str(session.native_identity_id)


@pytest.mark.asyncio
async def test_activity_touch_is_best_effort_and_never_breaks_authentication() -> None:
    material = issue_opaque_token()
    session = _snapshot(token_digest=material.digest, session_id=material.token_id)
    toucher = FakeSessionToucher(raises=True)
    authenticator = NativeSessionAuthenticator(
        session_reader=FakeSessionReader(session),
        session_toucher=toucher,
        clock=lambda: NOW,
    )

    subject = await authenticator.authenticate(NativeSessionEvidence(material.raw_token))

    assert subject.subject_id == str(session.native_identity_id)
    assert toucher.calls == [(session.session_id, 60)]


@pytest.mark.asyncio
async def test_revoked_webauthn_credential_invalidates_passkey_session() -> None:
    material = issue_opaque_token()
    session = _webauthn_snapshot(
        token_digest=material.digest,
        session_id=material.token_id,
        webauthn_credential_status=NativeCredentialStatus.REVOKED,
    )
    authenticator = NativeSessionAuthenticator(
        session_reader=FakeSessionReader(session),
        clock=lambda: NOW,
    )

    with pytest.raises(NativeCredentialRevoked):
        await authenticator.authenticate(NativeSessionEvidence(material.raw_token))


@pytest.mark.asyncio
async def test_passkey_session_propagates_phishing_resistant_evidence() -> None:
    material = issue_opaque_token()
    session = _webauthn_snapshot(token_digest=material.digest, session_id=material.token_id)
    authenticator = NativeSessionAuthenticator(
        session_reader=FakeSessionReader(session),
        clock=lambda: NOW,
    )

    subject = await authenticator.authenticate(NativeSessionEvidence(material.raw_token))

    assert subject.metadata["authentication_assurance"] == "phishing_resistant"
    assert subject.metadata["authentication_methods"] == "webauthn"
    assert subject.metadata["user_verified"] == "true"
    assert subject.metadata["recovery_derived"] == "false"
