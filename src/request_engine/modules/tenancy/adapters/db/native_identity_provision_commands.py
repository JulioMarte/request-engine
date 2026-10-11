import hashlib
import json
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from request_engine.modules.tenancy.application.commands.native_identity_provision import (
    NativeIdentityProvisionConflict,
    NativeIdentityProvisionForbidden,
    NativeIdentityProvisionInvalid,
    NativeIdentityProvisionResult,
    NativeIdentityProvisionUnavailable,
    ProvisionNativeIdentityCommand,
)
from request_engine.platform.db.session import SessionFactory, platform_actor_transaction
from request_engine.platform.security.context import PrincipalKind
from request_engine.platform.security.native_auth import (
    PasswordPolicyViolation,
    hash_password,
    hash_provision_password_intent_v1,
    normalize_login_handle,
)
from request_engine.platform.security.password_work import run_password_work
from request_engine.platform.security.platform_context import PlatformActorContext


class PostgresNativeIdentityProvisionCommands:
    def __init__(self, session_factory: SessionFactory, *, native_authority_id: UUID) -> None:
        self._session_factory = session_factory
        self._authority_id = native_authority_id

    async def provision_identity(
        self, actor: PlatformActorContext, command: ProvisionNativeIdentityCommand
    ) -> NativeIdentityProvisionResult:
        if actor.principal_kind is not PrincipalKind.HUMAN or not actor.allows(
            "platform.identity.provision"
        ):
            raise NativeIdentityProvisionForbidden()
        key = hashlib.sha256(command.idempotency_key.strip().encode()).hexdigest()
        scope = f"native-identity-provision:v1:{self._authority_id}:{actor.principal_id}:{key}"
        salt = hashlib.sha256(scope.encode()).digest()[:16]
        try:
            login = normalize_login_handle(command.login_handle)
            # Stable, operation-scoped Argon2 material avoids a cheap password oracle
            # in the durable fingerprint. Login credentials retain an independent random salt.
            password_intent = await run_password_work(
                hash_provision_password_intent_v1, command.password, salt=salt
            )
            verifier = await run_password_work(hash_password, command.password)
        except (PasswordPolicyViolation, ValueError) as exc:
            raise NativeIdentityProvisionInvalid() from exc
        intent = hashlib.sha256(
            json.dumps(
                ["native-identity-provision:v1", str(self._authority_id), login, password_intent],
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        try:
            async with platform_actor_transaction(self._session_factory, actor) as session:
                row = (
                    await session.execute(
                        text(
                            "SELECT * FROM request_platform.provision_native_identity("
                            "CAST(:authority AS uuid), CAST(:identity AS uuid),"
                            "CAST(:login AS text),"
                            "CAST(:credential AS uuid), CAST(:verifier AS text),"
                            "CAST(:key AS text), CAST(:intent AS text))"
                        ),
                        {
                            "authority": self._authority_id,
                            "identity": uuid4(),
                            "login": login,
                            "credential": uuid4(),
                            "verifier": verifier,
                            "key": key,
                            "intent": intent,
                        },
                    )
                ).one()
        except DBAPIError as exc:
            error = {
                "23505": NativeIdentityProvisionConflict,
                "22023": NativeIdentityProvisionInvalid,
                "42501": NativeIdentityProvisionForbidden,
                "28000": NativeIdentityProvisionForbidden,
                "40001": NativeIdentityProvisionForbidden,
                "55000": NativeIdentityProvisionUnavailable,
            }.get(str(getattr(exc.orig, "sqlstate", "")))
            if error is None:
                raise
            raise error() from None
        return NativeIdentityProvisionResult(native_identity_id=row[0], login_handle=row[1])
