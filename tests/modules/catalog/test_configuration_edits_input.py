"""Owner input admission for Catalog configuration edits (no database).

Protected risk: a blank/control-character label, an out-of-range duration, an
inexact price, an empty supersession or a repeated holiday date reaching the
authoritative handler (which would write or fingerprint invalid state). Each
rejected command must raise CatalogInvalidInput before the handler is called.
"""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from request_engine.modules.catalog.api.configuration_edit_router import (
    create_configuration_edit_router,
)
from request_engine.modules.catalog.api.operational_errors import register_input_error_handler
from request_engine.modules.catalog.application.commands import edit_offering
from request_engine.modules.catalog.application.commands import (
    remove_location_closures as closures,
)
from request_engine.modules.catalog.application.commands.update_location_operational_info import (
    validate_display_name,
)
from request_engine.modules.catalog.application.errors import CatalogInvalidInput
from request_engine.platform.security.context import ActorContext

pytestmark = [pytest.mark.unit]


class _Unreachable:
    calls = 0

    async def update_offering(self, command: Any) -> Any:
        self.calls += 1
        raise AssertionError("handler must not be reached")

    async def supersede_offering_version(self, command: Any) -> Any:
        self.calls += 1
        raise AssertionError("handler must not be reached")

    async def remove_organization_holidays(self, command: Any) -> Any:
        self.calls += 1
        raise AssertionError("handler must not be reached")

    async def deactivate_location_hours_exception(self, command: Any) -> Any:
        self.calls += 1
        raise AssertionError("handler must not be reached")


def _supersede(**overrides: object) -> edit_offering.SupersedeOfferingVersionCommand:
    values: dict[str, object] = {
        "organization_id": uuid4(),
        "principal_id": uuid4(),
        "authority_party_id": uuid4(),
        "offering_id": uuid4(),
        "expected_current_offering_version_id": uuid4(),
        "idempotency_key": "k",
        "duration_minutes": 30,
    }
    values.update(overrides)
    return edit_offering.SupersedeOfferingVersionCommand(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", ["", "   ", "a\x07b", "x" * 201])
def test_display_name_rejects_blank_control_and_overlong(value: str) -> None:
    with pytest.raises(CatalogInvalidInput):
        validate_display_name(value)


def test_display_name_is_trimmed() -> None:
    assert validate_display_name("  Sede Norte ") == "Sede Norte"


@pytest.mark.parametrize(
    "overrides",
    [
        {"duration_minutes": None, "booking_terms": None},
        {"duration_minutes": 0},
        {"duration_minutes": 1441},
        {"booking_terms": edit_offering.BaseTermsInput(Decimal("1.0000001"), "DOP")},
        {"booking_terms": edit_offering.BaseTermsInput(Decimal("-1"), "DOP")},
        {"booking_terms": edit_offering.BaseTermsInput(Decimal("10"), "dop")},
        {"idempotency_key": ""},
    ],
)
@pytest.mark.asyncio
async def test_invalid_supersession_never_reaches_the_handler(overrides: dict[str, object]) -> None:
    handler = _Unreachable()
    with pytest.raises(CatalogInvalidInput):
        await edit_offering.supersede_offering_version(handler, _supersede(**overrides))
    assert handler.calls == 0


@pytest.mark.asyncio
async def test_invalid_rename_and_holiday_removal_never_reach_handlers() -> None:
    handler = _Unreachable()
    with pytest.raises(CatalogInvalidInput):
        await edit_offering.update_offering(
            handler,
            edit_offering.UpdateOfferingCommand(
                uuid4(), uuid4(), uuid4(), uuid4(), "Limpieza", 0, "k"
            ),
        )
    for dates in ((), (date(2030, 1, 1), date(2030, 1, 1))):
        with pytest.raises(CatalogInvalidInput):
            await closures.remove_organization_holidays(
                handler,
                closures.RemoveOrganizationHolidaysCommand(uuid4(), uuid4(), uuid4(), dates, "k"),
            )
    with pytest.raises(CatalogInvalidInput):
        await closures.deactivate_location_hours_exception(
            handler,
            closures.DeactivateLocationHoursExceptionCommand(
                uuid4(), uuid4(), uuid4(), uuid4(), uuid4(), 0, "k"
            ),
        )
    assert handler.calls == 0


class _Resolver:
    def __init__(self, capabilities: frozenset[str]) -> None:
        self._actor = ActorContext(
            organization_id=uuid4(), principal_id=uuid4(), capabilities=capabilities
        )

    async def resolve_actor(self, request: object) -> ActorContext:
        del request
        return self._actor


@pytest.mark.asyncio
async def test_transport_rejects_fractional_json_price_and_unknown_fields() -> None:
    handler = _Unreachable()
    app = FastAPI()
    register_input_error_handler(app)
    app.include_router(
        create_configuration_edit_router(
            offering_handler=handler,
            version_handler=handler,
            exception_handler=handler,
            holidays_handler=handler,
            actor_resolver=_Resolver(frozenset({"catalog.manage"})),
        )
    )
    body = {
        "authority_party_id": str(uuid4()),
        "expected_current_offering_version_id": str(uuid4()),
        "booking_terms": {"amount": 19.9, "currency": "DOP"},
    }
    headers = {"Idempotency-Key": "k"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        fractional = await client.post(
            f"/v1/operations/offerings/{uuid4()}/versions", json=body, headers=headers
        )
        unknown = await client.patch(
            f"/v1/operations/offerings/{uuid4()}",
            json={
                "authority_party_id": str(uuid4()),
                "display_name": "X",
                "expected_revision": 1,
                "offering_key": "rekey",
            },
            headers=headers,
        )
        too_many = await client.post(
            "/v1/operations/organization/holidays:remove",
            json={
                "authority_party_id": str(uuid4()),
                "dates": [date(2030, 1, 1).isoformat()] * 367,
            },
            headers=headers,
        )
    assert fractional.status_code == 422
    assert unknown.status_code == 422
    assert too_many.status_code == 422
    assert handler.calls == 0
