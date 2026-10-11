"""Optional browser fixture: real console with a simulated upstream, not E2E."""

import os
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from request_engine.entrypoints.http.admin_console.app import create_admin_console_app
from request_engine.entrypoints.http.admin_console.client import ControlResponse
from request_engine.entrypoints.http.admin_console.settings import AdminConsoleSettings


class VisualControl:
    """Synthetic responses only; no real credentials, database or outbound calls."""

    async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
        payloads: dict[str, object] = {
            "/auth/native/sessions": {"access_token": "browser-fixture-bearer"},
            "/v1/platform/things": {"id": "fixture-created"},
            "/v1/platform/owner-invitations:enroll": {
                "invitation_id": "11111111-1111-4111-8111-111111111111",
                "native_identity_id": "22222222-2222-4222-8222-222222222222",
            },
            "/auth/native/sessions/current/recovery-codes": {
                "codes": ["browser-fixture-one-time-code"]
            },
            "/auth/native/sessions/current/recovery-readiness": {
                "active_webauthn_credentials": 0,
                "active_code_set": False,
                "remaining_codes": 0,
                "recovery_state": "not_prepared",
            },
            "/v1/platform/readiness": {
                "secret_store": "configured",
                "recovery_delivery_source": "managed",
                "backup_evidence": "verified",
                "restore_drill": "verified",
                "clone_fence": "fenced",
            },
            "/v1/platform/observability": {
                "alerts": [],
                "validation_success_total": 12,
                "validation_failure_total": 1,
                "provider_test_failures_total": 0,
                "secret_backend_failures_total": 0,
            },
        }
        return (
            ControlResponse(200, payloads[path], {})
            if path in payloads
            else ControlResponse(404, None, {})
        )

    async def openapi(self) -> dict[str, Any]:
        return {
            "paths": {
                "/v1/platform/things": {
                    "post": {
                        "operationId": "thing_create",
                        "summary": "Create fixture thing",
                        "tags": ["Platform things"],
                        "x-request-engine-capability": "thing.write",
                        "x-request-engine-kind": "command",
                        "x-request-engine-idempotency": "required",
                        "x-request-engine-exposure": "operator",
                        "x-request-engine-owner": "catalog",
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["name"],
                                        "properties": {"name": {"type": "string"}},
                                    }
                                }
                            }
                        },
                    }
                }
            }
        }

    async def aclose(self) -> None:
        pass


settings = AdminConsoleSettings(
    control_api_base_url="http://browser-fixture.invalid",
    session_secret=SecretStr("visual-fixture-session-key-only-for-ui-proof"),
    session_store_directory=Path(os.environ["ADMIN_BROWSER_SESSION_DIRECTORY"]),
    cookie_secure=False,
)
app = create_admin_console_app(settings, client=VisualControl())
