"""DEVELOPMENT-ONLY dev world for the local stack, created over public HTTP only.

It performs exactly what a person and the console would do, through the same
public contracts the black-box F-01 suite uses:

1. claim the UNCLAIMED instance (native identity + software passkey + recovery
   codes + finalize) on the private control plane;
2. sign the Platform Owner in with that passkey;
3. provision a native business owner and a dev Organization it controls;
4. provision and activate an integration principal whose id the worker uses to
   attribute scheduled writes.

No SQL, no internal imports, no fabricated principal. The passkey's private key
lives only in this process, so afterwards the owners sign in to the console with
their generated passwords. Only targets loopback URLs.
"""

from __future__ import annotations

import importlib
import json
import secrets
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

_REPO = Path(__file__).resolve().parents[2]
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
PLATFORM_LOGIN = "dev-platform-owner@example.invalid"
BUSINESS_LOGIN = "dev-business-owner@example.invalid"

Json = dict[str, object]


def _require_local(url: str) -> None:
    if urlsplit(url).hostname not in _LOCAL_HOSTS:
        raise SystemExit(f"refusing non-local seed target {url!r}: dev-only tooling")


def _call(
    method: str,
    url: str,
    *,
    payload: Json | None = None,
    auth: str | None = None,
    idempotency_key: str | None = None,
    organization_id: str | None = None,
    expected: tuple[int, ...] = (200,),
) -> Json:
    headers = {"Accept": "application/json"}
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    if auth is not None:
        headers["Authorization"] = auth
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    if organization_id is not None:
        headers["X-RE-Organization-ID"] = organization_id
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            status, text = response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        status, text = exc.code, exc.read().decode("utf-8", "replace")
    if status not in expected:
        raise RuntimeError(f"{method} {url} returned HTTP {status}: {text[:300]}")
    decoded: object = json.loads(text) if text.strip() else {}
    return cast(Json, decoded) if isinstance(decoded, dict) else {"items": decoded}


def _text(data: Json, key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"response is missing {key!r}")
    return value


def _public_key(data: Json) -> Json:
    value = data.get("public_key")
    if not isinstance(value, dict):
        raise RuntimeError("WebAuthn options are missing public_key")
    return cast(Json, value)


def _dev_password() -> str:
    return f"Dev!{secrets.token_hex(16)}Aa1"


def setup_required(control_url: str) -> bool:
    _require_local(control_url)
    return _call("GET", f"{control_url}/v1/setup").get("setup_required") is True


def seed(*, control_url: str, api_url: str, console_origin: str) -> Json:
    """Claim the instance and provision a dev organization plus worker principal."""

    for url in (control_url, api_url, console_origin):
        _require_local(url)
    sys.path.insert(0, str(_REPO / "tests" / "fixtures"))
    authenticator_module: Any = importlib.import_module("software_webauthn_authenticator")
    from fido2.utils import websafe_decode

    platform_password = _dev_password()
    setup = _call("POST", f"{control_url}/v1/setup/sessions", expected=(201,))
    setup_auth = f"Setup {_text(setup, 'token')}"
    _call(
        "POST",
        f"{control_url}/v1/setup/native-identity",
        auth=setup_auth,
        payload={"login_handle": PLATFORM_LOGIN, "password": platform_password},
        expected=(204,),
    )
    options = _public_key(
        _call("POST", f"{control_url}/v1/setup/webauthn/registration-options", auth=setup_auth)
    )
    rp_id = _text(cast(Json, options["rp"]), "id")
    authenticator = authenticator_module.SoftwareAuthenticator(rp_id=rp_id, origin=console_origin)
    credential = authenticator.registration_credential(
        challenge=websafe_decode(_text(options, "challenge")),
        public_key=options,
        user_verified=True,
    )
    _call(
        "POST",
        f"{control_url}/v1/setup/webauthn/registrations",
        auth=setup_auth,
        payload={"credential": credential},
        expected=(204,),
    )
    codes = _call(
        "POST", f"{control_url}/v1/setup/recovery-codes", auth=setup_auth, expected=(201,)
    )
    claim = _call(
        "POST",
        f"{control_url}/v1/setup:finalize",
        auth=setup_auth,
        idempotency_key="local-stack-claim-v1",
        payload={"claim_provenance": "local-stack:dev-seed"},
        expected=(201,),
    )
    workload_authority_id = _text(claim, "built_in_workload_authority_id")

    login_options = _public_key(
        _call(
            "POST",
            f"{control_url}/auth/native/webauthn/authentication-options",
            payload={"login_handle": PLATFORM_LOGIN},
        )
    )
    assertion = authenticator.authentication_credential(
        challenge=websafe_decode(_text(login_options, "challenge")), user_verified=True
    )
    platform_session = _call(
        "POST",
        f"{control_url}/auth/native/webauthn/sessions",
        payload={"login_handle": PLATFORM_LOGIN, "credential": assertion},
        expected=(201,),
    )
    platform_auth = f"Bearer {_text(platform_session, 'access_token')}"

    business_password = _dev_password()
    business_identity = _call(
        "POST",
        f"{control_url}/v1/platform/native-identities",
        auth=platform_auth,
        idempotency_key="local-stack-business-owner-v1",
        payload={"login_handle": BUSINESS_LOGIN, "password": business_password},
        expected=(201,),
    )
    organization = _call(
        "POST",
        f"{control_url}/v1/platform/organizations",
        auth=platform_auth,
        idempotency_key="local-stack-organization-v1",
        payload={
            "organization_key": "dev-local-business",
            "display_name": "Dev Local Business",
            "controller_native_identity_id": _text(business_identity, "native_identity_id"),
            "provenance_reference": "local-stack:dev-seed:organization",
        },
        expected=(201,),
    )
    organization_id = _text(organization, "organization_id")

    business_session = _call(
        "POST",
        f"{api_url}/auth/native/sessions",
        payload={"login_handle": BUSINESS_LOGIN, "password": business_password},
        expected=(201,),
    )
    business_auth = f"Bearer {_text(business_session, 'access_token')}"
    integration = _call(
        "POST",
        f"{api_url}/v1/integrations",
        auth=business_auth,
        organization_id=organization_id,
        idempotency_key="local-stack-worker-integration-v1",
        payload={
            "identity_authority_id": workload_authority_id,
            "credential_expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
            "provenance_reference": "local-stack:dev-seed:worker-integration",
        },
        expected=(201,),
    )
    worker_principal_id = _text(integration, "principal_id")
    _call(
        "POST",
        f"{api_url}/v1/integrations/{worker_principal_id}:activate",
        auth=business_auth,
        organization_id=organization_id,
        idempotency_key="local-stack-worker-integration-activate-v1",
        payload={
            "expected_revision": integration.get("authority_revision"),
            "provenance_reference": "local-stack:dev-seed:worker-integration-activate",
        },
    )
    return {
        "warning": "DEVELOPMENT ONLY - generated for this local stack, never reuse",
        "platform_owner": {"login": PLATFORM_LOGIN, "password": platform_password},
        "platform_owner_recovery_codes": codes.get("codes"),
        "business_owner": {"login": BUSINESS_LOGIN, "password": business_password},
        "organization_id": organization_id,
        "workload_authority_id": workload_authority_id,
        "worker_principal_id": worker_principal_id,
    }
