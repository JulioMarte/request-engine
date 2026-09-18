import json

import pytest
from fido2.utils import websafe_encode
from software_webauthn_authenticator import SoftwareAuthenticator

from request_engine.platform.security.webauthn import (
    WebAuthnInputError,
    WebAuthnPolicy,
    WebAuthnService,
    WebAuthnVerificationError,
    extract_authentication_challenge,
    extract_registration_challenge,
)

RP_ID = "localhost"
ORIGIN = "http://localhost:8000"
USER_NAME = "owner@example.test"


def _service() -> WebAuthnService:
    return WebAuthnService(
        WebAuthnPolicy(
            rp_id=RP_ID,
            rp_name="Request Engine",
            allowed_origins=frozenset({ORIGIN}),
        )
    )


def _authenticator(**overrides: object) -> SoftwareAuthenticator:
    params: dict[str, object] = {"rp_id": RP_ID, "origin": ORIGIN}
    params.update(overrides)
    return SoftwareAuthenticator(**params)  # type: ignore[arg-type]


def test_registration_and_authentication_round_trip() -> None:
    service = _service()
    authenticator = _authenticator()
    options = service.begin_registration(user_handle=authenticator.user_handle, user_name=USER_NAME)
    credential = authenticator.registration_credential(challenge=options.challenge)
    assert extract_registration_challenge(credential) == options.challenge

    verified = service.verify_registration(
        credential=credential, expected_challenge=options.challenge
    )
    assert verified.credential_id == authenticator.credential_id
    assert verified.user_verified is True
    assert verified.aaguid == "00" * 16
    assert verified.sign_count == 0

    auth_options = service.begin_authentication(allow_credential_ids=[verified.credential_id])
    assertion = authenticator.authentication_credential(challenge=auth_options.challenge)
    assert extract_authentication_challenge(assertion) == auth_options.challenge

    authenticated = service.verify_authentication(
        credential=assertion,
        expected_challenge=auth_options.challenge,
        credential_id=verified.credential_id,
        public_key=verified.public_key,
        aaguid=verified.aaguid,
        current_sign_count=verified.sign_count,
    )
    assert authenticated.credential_id == authenticator.credential_id
    assert authenticated.user_verified is True
    assert authenticated.new_sign_count == 1


def test_begin_options_are_json_serializable() -> None:
    service = _service()
    authenticator = _authenticator()
    options = service.begin_registration(user_handle=authenticator.user_handle, user_name=USER_NAME)
    payload = json.loads(json.dumps(options.public_key))
    assert payload["challenge"]
    assert payload["rp"]["id"] == RP_ID
    assert payload["user"]["name"] == USER_NAME

    auth_options = service.begin_authentication()
    auth_payload = json.loads(json.dumps(auth_options.public_key))
    assert auth_payload["rpId"] == RP_ID


def test_registration_rejects_missing_user_verification() -> None:
    service = _service()
    authenticator = _authenticator()
    options = service.begin_registration(user_handle=authenticator.user_handle, user_name=USER_NAME)
    credential = authenticator.registration_credential(
        challenge=options.challenge, user_verified=False
    )
    with pytest.raises(WebAuthnVerificationError) as exc:
        service.verify_registration(credential=credential, expected_challenge=options.challenge)
    assert exc.value.code == "webauthn_verification_failed"


def test_registration_rejects_wrong_origin() -> None:
    service = _service()
    authenticator = _authenticator(origin="http://evil.test")
    options = service.begin_registration(user_handle=authenticator.user_handle, user_name=USER_NAME)
    credential = authenticator.registration_credential(challenge=options.challenge)
    with pytest.raises(WebAuthnVerificationError):
        service.verify_registration(credential=credential, expected_challenge=options.challenge)


def test_registration_rejects_wrong_rp_id() -> None:
    service = _service()
    authenticator = _authenticator(rp_id="evil.test")
    options = service.begin_registration(user_handle=authenticator.user_handle, user_name=USER_NAME)
    credential = authenticator.registration_credential(challenge=options.challenge)
    with pytest.raises(WebAuthnVerificationError):
        service.verify_registration(credential=credential, expected_challenge=options.challenge)


def test_registration_rejects_wrong_expected_challenge() -> None:
    service = _service()
    authenticator = _authenticator()
    options = service.begin_registration(user_handle=authenticator.user_handle, user_name=USER_NAME)
    credential = authenticator.registration_credential(challenge=options.challenge)
    with pytest.raises(WebAuthnVerificationError):
        service.verify_registration(credential=credential, expected_challenge=b"\x01" * 32)


def test_authentication_rejects_tampered_signature() -> None:
    service = _service()
    authenticator = _authenticator()
    options = service.begin_registration(user_handle=authenticator.user_handle, user_name=USER_NAME)
    credential = authenticator.registration_credential(challenge=options.challenge)
    verified = service.verify_registration(
        credential=credential, expected_challenge=options.challenge
    )

    auth_options = service.begin_authentication(allow_credential_ids=[verified.credential_id])
    assertion = authenticator.authentication_credential(challenge=auth_options.challenge)
    response = dict(assertion["response"])
    response["signature"] = websafe_encode(b"\x00" * 64)
    tampered = {**assertion, "response": response}
    with pytest.raises(WebAuthnVerificationError):
        service.verify_authentication(
            credential=tampered,
            expected_challenge=auth_options.challenge,
            credential_id=verified.credential_id,
            public_key=verified.public_key,
            aaguid=verified.aaguid,
            current_sign_count=verified.sign_count,
        )


def test_authentication_rejects_wrong_challenge() -> None:
    service = _service()
    authenticator = _authenticator()
    options = service.begin_registration(user_handle=authenticator.user_handle, user_name=USER_NAME)
    credential = authenticator.registration_credential(challenge=options.challenge)
    verified = service.verify_registration(
        credential=credential, expected_challenge=options.challenge
    )
    auth_options = service.begin_authentication(allow_credential_ids=[verified.credential_id])
    assertion = authenticator.authentication_credential(challenge=auth_options.challenge)
    with pytest.raises(WebAuthnVerificationError):
        service.verify_authentication(
            credential=assertion,
            expected_challenge=b"\x02" * 32,
            credential_id=verified.credential_id,
            public_key=verified.public_key,
            aaguid=verified.aaguid,
            current_sign_count=0,
        )


def test_authentication_rejects_single_device_sign_count_regression() -> None:
    service = _service()
    authenticator = _authenticator()
    options = service.begin_registration(user_handle=authenticator.user_handle, user_name=USER_NAME)
    credential = authenticator.registration_credential(challenge=options.challenge)
    verified = service.verify_registration(
        credential=credential, expected_challenge=options.challenge
    )
    auth_options = service.begin_authentication(allow_credential_ids=[verified.credential_id])
    assertion = authenticator.authentication_credential(
        challenge=auth_options.challenge, increment=1
    )
    with pytest.raises(WebAuthnVerificationError) as exc:
        service.verify_authentication(
            credential=assertion,
            expected_challenge=auth_options.challenge,
            credential_id=verified.credential_id,
            public_key=verified.public_key,
            aaguid=verified.aaguid,
            current_sign_count=5,
        )
    assert exc.value.code == "webauthn_sign_count_regression"


def test_authentication_accepts_backup_eligible_counter_regression() -> None:
    service = _service()
    authenticator = _authenticator(backup_eligible=True)
    options = service.begin_registration(user_handle=authenticator.user_handle, user_name=USER_NAME)
    credential = authenticator.registration_credential(challenge=options.challenge)
    verified = service.verify_registration(
        credential=credential, expected_challenge=options.challenge
    )
    assert verified.backup_eligible is True
    auth_options = service.begin_authentication(allow_credential_ids=[verified.credential_id])
    assertion = authenticator.authentication_credential(
        challenge=auth_options.challenge, increment=1
    )
    authenticated = service.verify_authentication(
        credential=assertion,
        expected_challenge=auth_options.challenge,
        credential_id=verified.credential_id,
        public_key=verified.public_key,
        aaguid=verified.aaguid,
        current_sign_count=5,
    )
    assert authenticated.new_sign_count == 1


def test_authentication_accepts_zero_counters() -> None:
    service = _service()
    authenticator = _authenticator()
    options = service.begin_registration(user_handle=authenticator.user_handle, user_name=USER_NAME)
    credential = authenticator.registration_credential(challenge=options.challenge)
    verified = service.verify_registration(
        credential=credential, expected_challenge=options.challenge
    )
    auth_options = service.begin_authentication(allow_credential_ids=[verified.credential_id])
    assertion = authenticator.authentication_credential(
        challenge=auth_options.challenge, increment=0
    )
    authenticated = service.verify_authentication(
        credential=assertion,
        expected_challenge=auth_options.challenge,
        credential_id=verified.credential_id,
        public_key=verified.public_key,
        aaguid=verified.aaguid,
        current_sign_count=0,
    )
    assert authenticated.new_sign_count == 0


def test_extract_helpers_reject_malformed_credentials() -> None:
    with pytest.raises(WebAuthnInputError):
        extract_registration_challenge({"response": {}})
    with pytest.raises(WebAuthnInputError):
        extract_authentication_challenge({"response": {}})


def test_policy_rejects_empty_allowed_origins() -> None:
    with pytest.raises(ValueError):
        WebAuthnPolicy(rp_id=RP_ID, rp_name="Request Engine", allowed_origins=frozenset())
