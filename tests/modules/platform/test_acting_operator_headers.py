"""Trusted header parsing for the acting-operator relay (docs/v3/38 §9.1).

`X-RE-Platform` is recorded verbatim (<= 64 chars) and `X-RE-Acting-Operator`
must be a principal UUID. Invalid values fail closed with 422-style request
validation errors, consistent with the `Idempotency-Key` handling; absent
headers resolve to None and never authorize anything.
"""

from uuid import uuid4

import pytest
from fastapi import Request
from fastapi.exceptions import RequestValidationError

from request_engine.platform.security.acting_operator import (
    ACTING_OPERATOR_HEADER,
    PLATFORM_HEADER,
    validated_acting_operator,
    validated_platform,
)

_PLATFORM_BYTES = PLATFORM_HEADER.lower().encode()
_ACTING_BYTES = ACTING_OPERATOR_HEADER.lower().encode()


def _request(*headers: tuple[bytes, bytes]) -> Request:
    return Request({"type": "http", "headers": list(headers), "method": "POST", "path": "/"})


@pytest.mark.parametrize("raw", [b"   ", b"", b"x" * 65])
def test_invalid_platform_header_fails_422_style(raw: bytes) -> None:
    with pytest.raises(RequestValidationError) as caught:
        validated_platform(_request((_PLATFORM_BYTES, raw)))
    assert caught.value.errors()[0]["loc"] == ("header", PLATFORM_HEADER)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(b"whatsapp_bot", "whatsapp_bot"), (b"  reception_web  ", "reception_web")],
)
def test_valid_platform_header_is_stripped_and_recorded(raw: bytes, expected: str) -> None:
    assert validated_platform(_request((_PLATFORM_BYTES, raw))) == expected


def test_absent_platform_header_is_none() -> None:
    assert validated_platform(_request()) is None


def test_invalid_acting_operator_header_fails_422_style() -> None:
    with pytest.raises(RequestValidationError) as caught:
        validated_acting_operator(_request((_ACTING_BYTES, b"nope")))
    assert caught.value.errors()[0]["loc"] == ("header", ACTING_OPERATOR_HEADER)


def test_valid_acting_operator_header_parses_the_principal_uuid() -> None:
    principal_id = uuid4()
    parsed = validated_acting_operator(_request((_ACTING_BYTES, str(principal_id).encode())))
    assert parsed == principal_id


def test_absent_acting_operator_header_is_none() -> None:
    assert validated_acting_operator(_request()) is None
