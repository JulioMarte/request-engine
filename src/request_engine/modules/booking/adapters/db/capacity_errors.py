from typing import Never, Protocol, runtime_checkable

from sqlalchemy.exc import IntegrityError

from request_engine.modules.booking.application.errors import AppointmentUnavailable


@runtime_checkable
class _HasSqlState(Protocol):
    sqlstate: str | None


def normalize_capacity_integrity_error(exc: IntegrityError) -> Never:
    """Translate authoritative PostgreSQL capacity contention into domain unavailability.

    PostgreSQL SQLSTATE 23P01 is deliberately used by the local and shared-capacity
    invariant surfaces for a conflicting live commitment. The database exception
    may contain implementation detail, so callers must never expose it directly.
    """

    sqlstate = exc.orig.sqlstate if isinstance(exc.orig, _HasSqlState) else None
    if sqlstate == "23P01":
        raise AppointmentUnavailable("capacity unavailable") from None
    raise exc
