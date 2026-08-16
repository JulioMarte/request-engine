from __future__ import annotations

import asyncio
import json
from typing import cast

from fastapi import Request
from sqlalchemy.exc import IntegrityError

from request_engine.entrypoints.http.errors import integrity_error_handler


class _SqlStateError(Exception):
    def __init__(self, sqlstate: str, detail: str) -> None:
        super().__init__(detail)
        self.sqlstate = sqlstate


def _body_text(body: str | bytes | memoryview) -> str:
    if isinstance(body, str):
        return body
    return bytes(body).decode("utf-8")


def test_capacity_integrity_conflict_is_opaque_appointment_unavailable() -> None:
    foreign_secret = "foreign-org=2b3830d6-2d8d-4f8d-aefb-0da2fd4bfb25"
    original = _SqlStateError("23P01", f"capacity unavailable: {foreign_secret}")
    error = IntegrityError("INSERT capacity claim", {}, original)

    response = asyncio.run(integrity_error_handler(cast(Request, object()), error))
    raw = _body_text(response.body)

    assert response.status_code == 409
    payload = json.loads(raw)
    assert payload["error"]["code"] == "appointment_unavailable"
    assert payload["error"]["message"] == "the requested appointment is unavailable"
    assert payload["error"]["resolution"] == "refresh_and_retry"
    assert foreign_secret not in raw
