"""Narrow PostgreSQL conflict classification for S0d identity adoption."""

from sqlalchemy.exc import IntegrityError

_BINDING_PERSON_UNIQUE = "organization_person_binding_person_uq"
_UNIQUE_SQLSTATE = "23505"


def is_identity_already_adopted_violation(exc: IntegrityError) -> bool:
    if getattr(exc.orig, "sqlstate", None) != _UNIQUE_SQLSTATE:
        return False
    diagnostic = getattr(exc.orig, "diag", None)
    constraint = getattr(diagnostic, "constraint_name", None)
    if constraint is not None:
        return constraint == _BINDING_PERSON_UNIQUE
    return f'"{_BINDING_PERSON_UNIQUE}"' in str(exc.orig)
