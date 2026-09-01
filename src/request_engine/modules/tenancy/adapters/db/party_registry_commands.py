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
from request_engine.modules.tenancy.adapters.db.party_registry_correction_commands import (
    PostgresPartyCorrectionCommands,
)
from request_engine.modules.tenancy.adapters.db.party_registry_deactivation_commands import (
    PostgresPartyDeactivationCommands,
)


class PostgresPartyRegistryCommands(
    PostgresPartyRegistrationCommands,
    PostgresPartyContactPointCommands,
    PostgresPartyContactPointConfirmationCommands,
    PostgresPartyCorrectionCommands,
    PostgresPartyDeactivationCommands,
):
    """Tenancy-owned idempotent party registry commands.

    Composition of the per-capability command adapters: `parties.register`,
    `parties.add_contact_point`, `parties.confirm_contact_point` and the
    operator-granted correction surface (`parties.rename`,
    `parties.add_document`, `parties.deactivate_contact_point`,
    `parties.deactivate`). Each capability owns one Session, one explicit
    tenant transaction, standard idempotency replay and typed conflict
    mapping.
    """
