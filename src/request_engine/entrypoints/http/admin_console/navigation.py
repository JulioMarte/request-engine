"""Console navigation helpers shared by route modules."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import Request
from fastapi.responses import RedirectResponse


def login_redirect(request: Request) -> RedirectResponse:
    """Send a signed-out person to sign in, keeping their place for a GET page.

    Only the same-origin path and query of the current request are carried, so
    ``next`` can never point at another site. A form POST is not replayable after
    sign-in, so it goes to plain ``/login``.
    """

    if request.method.upper() != "GET":
        return RedirectResponse("/login", status_code=303)
    target = request.url.path
    if request.url.query:
        target = f"{target}?{request.url.query}"
    if not target.startswith("/") or target.startswith("//"):
        return RedirectResponse("/login", status_code=303)
    return RedirectResponse(f"/login?next={quote(target, safe='')}", status_code=303)


__all__ = ["login_redirect"]
