"""Sign-in returns a person to the console page they were on, and nowhere else."""

import pytest

from request_engine.entrypoints.http.admin_console.routes_auth import (
    _login_next,  # pyright: ignore[reportPrivateUsage]
)

pytestmark = [pytest.mark.unit]


@pytest.mark.parametrize(
    "target",
    [
        "/tenants/11111111-1111-4111-8111-111111111111/today",
        "/tenants/11111111-1111-4111-8111-111111111111/permissions-update?requested=x",
        "/account/security",
        "/staff-invitations/accept",
        "/resources/controller-policy-adoptions",
    ],
)
def test_console_pages_are_returned_to(target: str) -> None:
    assert _login_next(target) == target


@pytest.mark.parametrize(
    "target",
    [
        None,
        "",
        "https://evil.example/tenants/x",
        "//evil.example/tenants/x",
        "/\\evil.example/tenants/x",
        "/tenants/x\r\nSet-Cookie: a=b",
        "javascript:alert(1)",
        "/login",
        "/logout",
        "tenants/x",
        "/" + "a" * 600,
    ],
)
def test_anything_else_goes_home(target: object) -> None:
    assert _login_next(target) == "/"
