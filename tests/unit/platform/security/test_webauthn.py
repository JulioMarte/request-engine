import json
from typing import Any, cast

import pytest
from fido2 import cbor
from fido2.cose import CoseKey
from fido2.server import Fido2Server
from fido2.utils import websafe_encode
from fido2.webauthn import (
    CollectedClientData,
    PublicKeyCredentialRpEntity,
    PublicKeyCredentialUserEntity,
    UserVerificationRequirement,
)
from software_webauthn_authenticator import SoftwareAuthenticator

from request_engine.platform.security.webauthn import (
    CEREMONY_STATE_KEYS,
    RegistrationOptions,
    VerifiedRegistration,
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


def _registered(
    service: WebAuthnService, authenticator: SoftwareAuthenticator
) -> tuple[RegistrationOptions, VerifiedRegistration]:
    options = service.begin_registration(user_handle=authenticator.user_handle, user_name=USER_NAME)
    credential = authenticator.registration_credential(challenge=options.challenge)
    verified = service.verify_registration(
        credential=credential, expected_challenge=options.challenge
    )
    return options, verified


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
    )
    assert authenticated.credential_id == authenticator.credential_id
    assert authenticated.user_verified is True
    assert authenticated.sign_count == 1


def test_fido2_ceremony_state_contract_matches_reconstruction() -> None:
    """Pin the private fido2 state shape Request Engine reconstructs.

    ``register_begin``/``authenticate_begin`` return an untyped data bag that the
    library documents as "passed as is". Request Engine reconstructs exactly the
    keys the library reads so raw challenges never reach durable storage. If a 2.x
    minor changes that shape this test fails loudly instead of a security-relevant
    key being silently dropped.
    """

    server: Any = cast(
        "Any", Fido2Server(PublicKeyCredentialRpEntity(name="Request Engine", id=RP_ID))
    )
    user = PublicKeyCredentialUserEntity(name=USER_NAME, id=b"\x00" * 16)
    challenge = b"\x11" * 32

    _creation, registration_state = server.register_begin(
        user,
        challenge=challenge,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    assert set(registration_state) == set(CEREMONY_STATE_KEYS)
    assert registration_state["challenge"] == websafe_encode(challenge)

    _request, authentication_state = server.authenticate_begin(
        challenge=challenge,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    assert set(authentication_state) == set(CEREMONY_STATE_KEYS)
    assert authentication_state["challenge"] == websafe_encode(challenge)


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


def test_authentication_rejects_missing_user_verification() -> None:
    service = _service()
    authenticator = _authenticator()
    _options, verified = _registered(service, authenticator)
    auth_options = service.begin_authentication(allow_credential_ids=[verified.credential_id])
    assertion = authenticator.authentication_credential(
        challenge=auth_options.challenge, user_verified=False
    )
    with pytest.raises(WebAuthnVerificationError):
        service.verify_authentication(
            credential=assertion,
            expected_challenge=auth_options.challenge,
            credential_id=verified.credential_id,
            public_key=verified.public_key,
            aaguid=verified.aaguid,
        )


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
    _options, verified = _registered(service, authenticator)

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
        )


def test_authentication_rejects_wrong_challenge() -> None:
    service = _service()
    authenticator = _authenticator()
    _options, verified = _registered(service, authenticator)
    auth_options = service.begin_authentication(allow_credential_ids=[verified.credential_id])
    assertion = authenticator.authentication_credential(challenge=auth_options.challenge)
    with pytest.raises(WebAuthnVerificationError):
        service.verify_authentication(
            credential=assertion,
            expected_challenge=b"\x02" * 32,
            credential_id=verified.credential_id,
            public_key=verified.public_key,
            aaguid=verified.aaguid,
        )


def test_authentication_rejects_malformed_stored_public_key() -> None:
    service = _service()
    authenticator = _authenticator()
    _options, verified = _registered(service, authenticator)
    auth_options = service.begin_authentication(allow_credential_ids=[verified.credential_id])
    assertion = authenticator.authentication_credential(challenge=auth_options.challenge)
    with pytest.raises(WebAuthnVerificationError):
        service.verify_authentication(
            credential=assertion,
            expected_challenge=auth_options.challenge,
            credential_id=verified.credential_id,
            public_key=b"\x00",
            aaguid=verified.aaguid,
        )


def test_authentication_surfaces_backup_and_zero_counters_without_deciding_policy() -> None:
    service = _service()
    authenticator = _authenticator(backup_eligible=True)
    _options, verified = _registered(service, authenticator)
    assert verified.backup_eligible is True

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
    )
    assert authenticated.sign_count == 0
    assert authenticated.backup_eligible is True


def test_extract_helpers_reject_malformed_credentials() -> None:
    with pytest.raises(WebAuthnInputError):
        extract_registration_challenge({"response": {}})
    with pytest.raises(WebAuthnInputError):
        extract_authentication_challenge({"response": {}})


def test_policy_rejects_empty_allowed_origins() -> None:
    with pytest.raises(ValueError):
        WebAuthnPolicy(rp_id=RP_ID, rp_name="Request Engine", allowed_origins=frozenset())


def test_policy_rejects_non_none_attestation_without_verifier() -> None:
    with pytest.raises(ValueError):
        WebAuthnPolicy(
            rp_id=RP_ID,
            rp_name="Request Engine",
            allowed_origins=frozenset({ORIGIN}),
            attestation="direct",
        )


def test_authentication_rejects_unsupported_cose_algorithm() -> None:
    service = _service()
    authenticator = _authenticator()
    _options, verified = _registered(service, authenticator)
    auth_options = service.begin_authentication(allow_credential_ids=[verified.credential_id])
    assertion = authenticator.authentication_credential(challenge=auth_options.challenge)
    unsupported_public_key = cbor.encode(CoseKey.parse({1: 3, 3: -999, -1: 1}))
    with pytest.raises(WebAuthnVerificationError):
        service.verify_authentication(
            credential=assertion,
            expected_challenge=auth_options.challenge,
            credential_id=verified.credential_id,
            public_key=unsupported_public_key,
            aaguid=verified.aaguid,
        )


def test_extract_rejects_malformed_authenticator_data() -> None:
    client_data = CollectedClientData.create(  # pyright: ignore[reportUnknownMemberType]
        "webauthn.get", b"\x01" * 32, ORIGIN
    )
    malformed = {
        "id": websafe_encode(b"\x01" * 32),
        "rawId": websafe_encode(b"\x01" * 32),
        "type": "public-key",
        "response": {
            "clientDataJSON": websafe_encode(bytes(client_data)),
            # ED flag set with no extension bytes -> the bundled CBOR decoder
            # raises IndexError, which must surface as a typed input error.
            "authenticatorData": websafe_encode(b"\x00" * 32 + b"\x80" + b"\x00" * 4),
            "signature": websafe_encode(b"\x00" * 64),
        },
    }
    with pytest.raises(WebAuthnInputError):
        extract_authentication_challenge(malformed)
