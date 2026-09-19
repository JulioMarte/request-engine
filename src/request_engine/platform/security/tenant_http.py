from uuid import UUID

from fastapi import Request

ORGANIZATION_HEADER = "X-RE-Organization-ID"


class TenantContextInvalid(ValueError):
    pass


def tenant_context(request: Request) -> UUID:
    """Read an explicit tenant selector without treating it as authority."""

    value = request.headers.get(ORGANIZATION_HEADER)
    if value is None or not value.strip():
        from request_engine.platform.security.identity_resolution import TenantContextRequired

        raise TenantContextRequired(f"{ORGANIZATION_HEADER} is required")
    try:
        return UUID(value.strip())
    except ValueError as exc:
        raise TenantContextInvalid(f"{ORGANIZATION_HEADER} must be a UUID") from exc
