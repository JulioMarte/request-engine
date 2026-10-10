"""Input bounds for the operator-invoked WebAuthn challenge retention pass."""

from typing import Any

import psycopg
from psycopg import Connection

MIN_RETENTION_SECONDS = 24 * 60 * 60
DEFAULT_RETENTION_SECONDS = 7 * 24 * 60 * 60
MAX_RETENTION_SECONDS = 90 * 24 * 60 * 60
DEFAULT_BATCH_SIZE = 500
MAX_BATCH_SIZE = 1000
_CALLER_ROLE = "request_webauthn_retention"


def validate_retention_configuration(
    retention_seconds: object, batch_size: object
) -> tuple[int, int]:
    """Reject coercible-but-ambiguous configuration before database work."""

    if type(retention_seconds) is not int:
        raise ValueError("retention_seconds must be an integer")
    if not MIN_RETENTION_SECONDS <= retention_seconds <= MAX_RETENTION_SECONDS:
        raise ValueError("retention_seconds must be between 86400 and 7776000")
    if type(batch_size) is not int:
        raise ValueError("batch_size must be an integer")
    if not 1 <= batch_size <= MAX_BATCH_SIZE:
        raise ValueError("batch_size must be between 1 and 1000")
    return retention_seconds, batch_size


def parse_integer_setting(value: object, *, name: str) -> int:
    """Parse deployment-provided integer text without accepting float spellings."""

    if type(value) is not str or not value or not value.isascii() or not value.isdecimal():
        raise ValueError(f"{name} must be a decimal integer")
    return int(value)


def delete_retained_webauthn_challenges(
    connection: Connection[Any], *, retention_seconds: object, batch_size: object
) -> int:
    """Run one bounded batch; caller must already have selected the maintenance role."""

    retention, maximum = validate_retention_configuration(retention_seconds, batch_size)
    row = connection.execute(
        "SELECT request_auth.delete_retained_webauthn_challenges(%s, %s)",
        (retention, maximum),
    ).fetchone()
    if row is None or type(row[0]) is not int:
        raise RuntimeError("challenge retention function returned an invalid count")
    return row[0]


def run_retention_pass(dsn: str, *, retention_seconds: object, batch_size: object) -> int:
    """Execute one pass using a LOGIN explicitly granted the NOLOGIN caller role."""

    retention, maximum = validate_retention_configuration(retention_seconds, batch_size)
    with psycopg.connect(dsn, connect_timeout=5) as connection, connection.transaction():
        caller = connection.execute(
            """
            SELECT login.rolcanlogin, login.rolsuper, login.rolcreatedb,
                   login.rolcreaterole, login.rolreplication, login.rolbypassrls,
                   login.rolinherit, login.rolconfig,
                   membership.membership_count, membership.only_retention_role
              FROM pg_roles AS login
              CROSS JOIN LATERAL (
                    SELECT count(*) AS membership_count,
                           bool_and(
                               granted.rolname = %s
                               AND NOT member.admin_option
                               AND NOT member.inherit_option
                               AND member.set_option
                           ) AS only_retention_role
                      FROM pg_auth_members AS member
                      JOIN pg_roles AS granted ON granted.oid = member.roleid
                     WHERE member.member = login.oid
              ) AS membership
             WHERE login.rolname = session_user
            """,
            (_CALLER_ROLE,),
        ).fetchone()
        if caller != (True, False, False, False, False, False, False, None, 1, True):
            raise PermissionError("maintenance DSN must be a dedicated non-inheriting login")
        connection.execute("SET LOCAL statement_timeout = '30s'")
        connection.execute("SET LOCAL lock_timeout = '2s'")
        connection.execute(f"SET LOCAL ROLE {_CALLER_ROLE}")
        return delete_retained_webauthn_challenges(
            connection,
            retention_seconds=retention,
            batch_size=maximum,
        )
