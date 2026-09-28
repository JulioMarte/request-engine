from __future__ import annotations

import hashlib
import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from request_engine.modules.platform_configuration.application.configuration import (
    PlatformConfigurationConflict,
    PlatformConfigurationForbidden,
    PlatformConfigurationInvalid,
    PlatformConfigurationNotFound,
    PlatformConfigurationRevisionConflict,
)
from request_engine.platform.db.session import SessionFactory, platform_actor_transaction
from request_engine.platform.security.platform_context import PlatformActorContext


class PostgresProviderTestRecorder:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def record(
        self,
        actor: PlatformActorContext,
        *,
        configuration_kind: str,
        revision: int,
        expected_binding_revision: int | None,
        expected_backend_version: int | None,
        outcome: str,
        detail_code: str,
        idempotency_key: str,
        destination: str,
    ) -> UUID:
        intent_digest = hashlib.sha256(
            json.dumps(
                {
                    "configuration_kind": configuration_kind,
                    "revision": revision,
                    "expected_binding_revision": expected_binding_revision,
                    "expected_backend_version": expected_backend_version,
                    "destination": destination,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        key_digest = hashlib.sha256(idempotency_key.strip().encode()).hexdigest()
        try:
            async with platform_actor_transaction(self._session_factory, actor) as session:
                fact_id = await session.scalar(
                    text(
                        "SELECT request_platform.record_platform_provider_test("
                        "CAST(:kind AS text), CAST(:revision AS bigint), "
                        "CAST(:binding_revision AS bigint), CAST(:backend_version AS integer), "
                        "CAST(:outcome AS text), CAST(:detail_code AS text), "
                        "CAST(:key_digest AS text), CAST(:intent_digest AS text))"
                    ),
                    {
                        "kind": configuration_kind,
                        "revision": revision,
                        "binding_revision": expected_binding_revision,
                        "backend_version": expected_backend_version,
                        "outcome": outcome,
                        "detail_code": detail_code,
                        "key_digest": key_digest,
                        "intent_digest": intent_digest,
                    },
                )
        except DBAPIError as exc:
            state = str(getattr(exc.orig, "sqlstate", ""))
            if state == "P0002":
                raise PlatformConfigurationNotFound() from None
            if state in {"42501", "28000"}:
                raise PlatformConfigurationForbidden() from None
            if state in {"22023", "23514"}:
                raise PlatformConfigurationInvalid() from None
            if state == "23505":
                raise PlatformConfigurationConflict() from None
            if state in {"40001", "40P01"}:
                raise PlatformConfigurationRevisionConflict() from None
            raise
        return UUID(str(fact_id))
