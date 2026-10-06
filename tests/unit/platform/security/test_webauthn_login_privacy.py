"""Handle login never exposes credential metadata or authenticates a different handle."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from software_webauthn_authenticator import SoftwareAuthenticator

from request_engine.platform.security.native_webauthn_auth import (
    NativeWebAuthnAuthService,
    WebAuthnCeremonyError,
    WebAuthnCeremonyStore,
    WebAuthnChallengeScope,
    WebAuthnCredentialRecord,
)
from request_engine.platform.security.native_webauthn_login import NativeWebAuthnLoginService
from request_engine.platform.security.webauthn import (
    WebAuthnPolicy,
    WebAuthnService,
    public_key_to_json,
)

pytestmark = [pytest.mark.unit, pytest.mark.security, pytest.mark.adversarial]


@pytest.mark.asyncio
async def test_every_handle_options_is_discoverable_without_reading_identity_credentials() -> None:
    store = Mock(spec=WebAuthnCeremonyStore)
    store.create_challenge = AsyncMock(return_value=True)
    identities = Mock()
    identities.read_active_webauthn_identity = AsyncMock()
    login = NativeWebAuthnLoginService(
        webauthn=NativeWebAuthnAuthService(
            policy=WebAuthnPolicy(
                rp_id="localhost", rp_name="Test", allowed_origins=frozenset({"https://localhost"})
            ),
            store=store,
        ),
        identities=identities,
        decoy_key=b"test-only",
    )
    authority = uuid4()
    options = [
        public_key_to_json(
            (
                await login.begin_login(identity_authority_id=authority, login_handle=handle)
            ).public_key
        )
        for handle in (None, "known@example.test", "absent@example.test")
    ]
    assert all(not option.get("allowCredentials") for option in options)
    assert all(
        {k: v for k, v in option.items() if k != "challenge"}
        == {k: v for k, v in options[0].items() if k != "challenge"}
        for option in options
    )
    identities.read_active_webauthn_identity.assert_not_awaited()
    store.read_credentials.assert_not_called()
    assert store.create_challenge.await_count == 3


@pytest.mark.asyncio
async def test_real_assertion_cannot_authenticate_another_intended_handle() -> None:
    policy = WebAuthnPolicy(
        rp_id="localhost", rp_name="Test", allowed_origins=frozenset({"https://localhost"})
    )
    crypto = WebAuthnService(policy)
    key = SoftwareAuthenticator(rp_id="localhost", origin="https://localhost")
    registration = crypto.begin_registration(user_handle=key.user_handle, user_name="owner")
    verified = crypto.verify_registration(
        credential=key.registration_credential(
            challenge=registration.challenge, user_verified=True
        ),
        expected_challenge=registration.challenge,
    )
    store = Mock(spec=WebAuthnCeremonyStore)
    store.create_challenge = AsyncMock(return_value=True)
    store.read_challenge = AsyncMock(
        return_value=WebAuthnChallengeScope(
            None, None, None, datetime.now(UTC) + timedelta(minutes=1)
        )
    )
    store.read_credential = AsyncMock(
        return_value=WebAuthnCredentialRecord(
            uuid4(),
            uuid4(),
            verified.credential_id,
            verified.public_key,
            verified.sign_count,
            verified.aaguid,
            verified.backup_eligible,
            verified.backup_state,
            True,
            "active",
        )
    )
    identities = Mock()
    identities.read_active_webauthn_identity = AsyncMock(return_value=uuid4())
    login = NativeWebAuthnLoginService(
        webauthn=NativeWebAuthnAuthService(policy=policy, store=store),
        identities=identities,
        decoy_key=b"test-only",
    )
    started = await login.begin_login(
        identity_authority_id=uuid4(), login_handle="other@example.test"
    )
    with pytest.raises(WebAuthnCeremonyError, match="webauthn_credential_unknown"):
        await login.complete_login(
            identity_authority_id=uuid4(),
            login_handle="other@example.test",
            credential=key.authentication_credential(
                challenge=started.challenge, user_verified=True
            ),
        )
    store.finalize_discoverable_authentication.assert_not_called()
