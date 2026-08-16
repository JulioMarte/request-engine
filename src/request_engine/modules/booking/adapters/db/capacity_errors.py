from collections.abc import Awaitable, Callable
from functools import wraps
from typing import ParamSpec, Protocol, TypeVar, runtime_checkable

from sqlalchemy.exc import IntegrityError

from request_engine.modules.booking.application.errors import AppointmentUnavailable

P = ParamSpec("P")
R = TypeVar("R")


@runtime_checkable
class _HasSqlState(Protocol):
    sqlstate: str | None


def normalize_capacity_integrity_error(exc: IntegrityError) -> None:
    """Translate authoritative PostgreSQL capacity contention into domain unavailability.

    PostgreSQL SQLSTATE 23P01 is deliberately used by the local and shared-capacity
    invariant surfaces for a conflicting live commitment. The database exception
    may contain implementation detail, so callers must never expose it directly.
    """

    sqlstate = exc.orig.sqlstate if isinstance(exc.orig, _HasSqlState) else None
    if sqlstate == "23P01":
        raise AppointmentUnavailable("capacity unavailable") from None
    raise exc


def translate_capacity_integrity_errors(
    function: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R]]:
    """Keep PostgreSQL race enforcement behind the Booking domain error contract."""

    @wraps(function)
    async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await function(*args, **kwargs)
        except IntegrityError as exc:
            normalize_capacity_integrity_error(exc)
            raise AssertionError("unreachable")

    return wrapped
