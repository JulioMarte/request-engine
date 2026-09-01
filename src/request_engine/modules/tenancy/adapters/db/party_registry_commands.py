"""Published tenancy party registry command adapter (parties.* capabilities)."""

from request_engine.modules.tenancy.adapters.db.party_contact_point_commands import (
    PostgresPartyContactPointCommands,
)
from request_engine.modules.tenancy.adapters.db.party_contact_point_confirmation_commands import (
    PostgresPartyContactPointConfirmationCommands,
)
from request_engine.modules.tenancy.adapters.db.party_registration_commands import (
    PostgresPartyRegistrationCommands,
)


class PostgresPartyRegistryCommands(
    PostgresPartyRegistrationCommands,
    PostgresPartyContactPointCommands,
    PostgresPartyContactPointConfirmationCommands,
):
    """Tenancy-owned idempotent party registry commands.

    Composition of the per-capability command adapters: `parties.register`,
    `parties.add_contact_point` and `parties.confirm_contact_point`. Each
    capability owns one Session, one explicit tenant transaction, standard
    idempotency replay and typed conflict mapping.
    """
