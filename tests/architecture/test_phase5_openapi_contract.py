from fastapi import APIRouter, FastAPI

from request_engine.platform.http.capability_routes import add_capability_route


def test_public_capability_route_exports_stable_machine_metadata() -> None:
    router = APIRouter()

    async def endpoint() -> dict[str, bool]:
        return {"ok": True}

    add_capability_route(
        router,
        "/appointments/{reservation_id}/cancel",
        endpoint,
        capability="appointments.cancel",
        methods=["POST"],
    )
    app = FastAPI()
    app.include_router(router)
    operation = app.openapi()["paths"]["/appointments/{reservation_id}/cancel"]["post"]

    assert operation["operationId"] == "appointments_cancel"
    assert operation["x-request-engine-capability"] == "appointments.cancel"
    assert operation["x-request-engine-schema-version"] == 1
    assert operation["x-request-engine-idempotency"] == "required"
    assert operation["x-request-engine-expected-revision"] == "required"
    assert operation["x-request-engine-exposure"] == "public"
    assert operation["x-request-engine-party-scope"] == "appointments.manage"
    assert operation["x-request-engine-override-capability"] == "appointments.subject_override"


def test_internal_capability_route_is_not_published_in_openapi() -> None:
    router = APIRouter()

    async def endpoint() -> dict[str, bool]:
        return {"ok": True}

    add_capability_route(
        router,
        "/requests/{request_id}/complete",
        endpoint,
        capability="requests.complete",
        methods=["POST"],
    )
    app = FastAPI()
    app.include_router(router)

    assert "/requests/{request_id}/complete" not in app.openapi()["paths"]
