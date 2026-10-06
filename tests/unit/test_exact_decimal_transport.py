"""Lossless admission and honest schemas for the three monetary request DTOs."""

import json
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from request_engine.modules.booking.api.operational_terms_router import (
    ContextTermsBody,
    SupersedeTermsBody,
)
from request_engine.modules.catalog.api.operational_schedule_router import BaseTermsBody

pytestmark = [pytest.mark.unit, pytest.mark.contract]


@pytest.mark.parametrize("model", [BaseTermsBody, ContextTermsBody, SupersedeTermsBody])
def test_money_transport_schema_and_exact_admission(
    model: type[BaseTermsBody] | type[ContextTermsBody] | type[SupersedeTermsBody],
) -> None:
    payload: dict[str, object] = {"authority_party_id": uuid4(), "currency": "USD"}
    if model is not BaseTermsBody:
        payload["effective_from"] = "2026-10-06T00:00:00Z"
    if model is ContextTermsBody:
        payload.update(resource_location_assignment_id=uuid4(), offering_version_id=uuid4())
    if model is SupersedeTermsBody:
        payload["expected_current_revision"] = 1
    for value in ("99999999999999.111111", 19, Decimal("19.111111")):
        body = model.model_validate({**payload, "amount": value})
        assert body.amount == Decimal(value)
    for value in (True, False, 1.0, json.loads("99999999999999.111111")):
        with pytest.raises(ValidationError):
            model.model_validate({**payload, "amount": value})
    schema = model.model_json_schema(mode="validation")["properties"]["amount"]
    types = {entry["type"] for entry in schema["anyOf"]}
    assert types == (
        {"string", "integer"} if model is BaseTermsBody else {"string", "integer", "null"}
    )
    if model is BaseTermsBody:
        with pytest.raises(ValidationError):
            model.model_validate({**payload, "amount": None})
    else:
        body = model.model_validate(
            {**payload, "amount": None, "currency": None, "bookable": False}
        )
        assert body.amount is None
