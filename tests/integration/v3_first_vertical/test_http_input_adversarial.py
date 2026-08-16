from uuid import UUID, uuid4

import pytest
from fastapi import Request
from httpx import ASGITransport, AsyncClient, Response

from request_engine.entrypoints.http.app import create_app
from request_engine.entrypoints.http.security import AuthenticationRequired
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

_FULL_CAPABILITIES = frozenset(
    {
        "business.read",
        "catalog.read",
        "booking.find_slots",
        "booking.book_appointment",
        "booking.read",
        "booking.cancel_reservation",
        "booking.reschedule_reservation",
        "appointments.subject_override",
        "queue.read",
        "queue.join",
        "queue.leave",
        "queue.call_next",
        "queue.subject_override",
    }
)
_LEAK_TOKENS = (
    "asyncpg",
    "psycopg",
    "sqlalchemy",
    "traceback",
    "request_engine.",
    "constraint",
    "select ",
    "insert ",
    "update ",
    "delete ",
)


class _BearerResolver:
    def __init__(self, actor: ActorContext) -> None:
        self._actor = actor

    async def resolve_actor(self, request: Request) -> ActorContext:
        if request.headers.get("authorization") != "Bearer adversarial":
            raise AuthenticationRequired
        return self._actor


def _client(session_factory: SessionFactory) -> AsyncClient:
    actor = ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        capabilities=_FULL_CAPABILITIES,
    )
    app = create_app(
        session_factory=session_factory,
        actor_resolver=_BearerResolver(actor),
        appointment_option_signing_key=b"phase6-http-adversarial-test-key",
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _assert_validation_failure(response: Response) -> None:
    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "validation_failed"
    assert payload["error"]["details"]["fields"]

    correlation_id = response.headers.get("X-Correlation-ID")
    assert correlation_id is not None
    UUID(correlation_id)

    rendered = response.text.lower()
    leaked = [token for token in _LEAK_TOKENS if token in rendered]
    assert not leaked, f"validation response leaked implementation detail(s): {leaked}"


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_http_validation_rejects_malformed_and_mass_assignment_inputs_without_leaks(
    session_factory: SessionFactory,
) -> None:
    auth = {"Authorization": "Bearer adversarial"}
    reservation_id = uuid4()

    async with _client(session_factory) as client:
        responses = [
            await client.get(
                "/v1/appointments/slots",
                params={
                    "offering_version_id": "not-a-uuid",
                    "window_start": "not-a-date",
                    "window_end": "2026-08-17T16:00:00Z",
                },
                headers=auth,
            ),
            await client.get(
                "/v1/appointments/slots",
                params={
                    "offering_version_id": str(uuid4()),
                    "window_start": "2026-08-17T13:00:00Z",
                    "window_end": "2026-08-17T16:00:00Z",
                    "limit": "201",
                },
                headers=auth,
            ),
            await client.get("/v1/appointments/not-a-uuid", headers=auth),
            await client.post(
                "/v1/appointments",
                json={
                    "option_id": "opaque-option",
                    "subject_party_id": str(uuid4()),
                    "organization_id": str(uuid4()),
                },
                headers={**auth, "Idempotency-Key": "mass-assignment"},
            ),
            await client.post(
                "/v1/appointments",
                json={"option_id": "opaque-option", "subject_party_id": "not-a-uuid"},
                headers={**auth, "Idempotency-Key": "malformed-subject"},
            ),
            await client.post(
                f"/v1/appointments/{reservation_id}/cancel",
                json={"expected_revision": 0},
                headers={**auth, "Idempotency-Key": "zero-revision"},
            ),
            await client.post(
                f"/v1/appointments/{reservation_id}/cancel",
                json={"expected_revision": 1, "unexpected": "field"},
                headers={**auth, "Idempotency-Key": "extra-field"},
            ),
            await client.post(
                f"/v1/appointments/{reservation_id}/cancel",
                json={"expected_revision": 1},
                headers={**auth, "Idempotency-Key": "x" * 251},
            ),
        ]

    assert len(responses) == 8
    for response in responses:
        _assert_validation_failure(response)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_http_validation_does_not_accept_oversized_booking_option(
    session_factory: SessionFactory,
) -> None:
    auth = {
        "Authorization": "Bearer adversarial",
        "Idempotency-Key": "oversized-option",
    }
    async with _client(session_factory) as client:
        response = await client.post(
            "/v1/appointments",
            json={
                "option_id": "x" * 8193,
                "subject_party_id": str(uuid4()),
            },
            headers=auth,
        )

    assert response.status_code == 422
    _assert_validation_failure(response)
