"""Published tenancy staff administrative contact command adapter (§9.2)."""

from request_engine.modules.tenancy.adapters.db.principal_contact_confirmation_commands import (
    PostgresPrincipalContactConfirmationCommands,
)
from request_engine.modules.tenancy.adapters.db.principal_contact_registration_commands import (
    PostgresPrincipalContactRegistrationCommands,
)
from request_engine.modules.tenancy.adapters.db.principal_contact_verification_commands import (
    PostgresPrincipalContactVerificationCommands,
)


class PostgresPrincipalContactCommands(
    PostgresPrincipalContactRegistrationCommands,
    PostgresPrincipalContactVerificationCommands,
    PostgresPrincipalContactConfirmationCommands,
):
    """Tenancy-owned idempotent staff administrative contact commands.

    Composition of the per-capability command adapters:
    `staff.manage_own_admin_contact` (register + verification request) and
    `staff.confirm_own_admin_contact` (one-time code confirmation). Each
    capability owns one Session, one explicit tenant transaction, standard
    idempotency replay and typed error mapping; the verification request is
    the only outbox emitter.
    """
