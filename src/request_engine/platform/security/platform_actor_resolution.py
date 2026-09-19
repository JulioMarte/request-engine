from uuid import UUID

from request_engine.platform.security.context import PrincipalKind
from request_engine.platform.security.platform_context import PlatformActorContext
from request_engine.platform.security.principal_authority import (
    PlatformPrincipalAuthorityReader,
    PrincipalAuthorityMaterializationError,
)


class PlatformPrincipalResolutionUnavailable(RuntimeError):
    """Platform Principal authority cannot be resolved safely at this time."""


class PlatformPrincipalActorResolver:
    """Materialize a post-binding platform actor from RE-owned standing authority."""

    def __init__(self, authority_reader: PlatformPrincipalAuthorityReader) -> None:
        self._authority_reader = authority_reader

    async def resolve_platform_actor(
        self,
        *,
        principal_id: UUID,
        authentication_method: str,
        credential_id: str | None = None,
        technical_principal_id: UUID | None = None,
        interaction_id: str | None = None,
    ) -> PlatformActorContext | None:
        try:
            authority = await self._authority_reader.read_platform_principal_authority(
                principal_id=principal_id
            )
        except PrincipalAuthorityMaterializationError as exc:
            raise PlatformPrincipalResolutionUnavailable() from exc
        if authority is None:
            return None

        try:
            principal_kind = PrincipalKind(authority.principal_kind)
        except ValueError as exc:
            raise PlatformPrincipalResolutionUnavailable() from exc

        return PlatformActorContext(
            principal_id=principal_id,
            capabilities=authority.capabilities,
            authority_revision=authority.authority_revision,
            principal_kind=principal_kind,
            authentication_method=authentication_method,
            credential_id=credential_id,
            technical_principal_id=technical_principal_id,
            interaction_id=interaction_id,
        )
