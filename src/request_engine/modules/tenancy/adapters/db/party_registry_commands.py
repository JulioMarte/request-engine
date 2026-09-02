"""Published tenancy party registry command adapter (parties.* capabilities)."""

from request_engine.modules.tenancy.adapters.db.party_administrative_identifier_commands import (
    PostgresPartyAdministrativeIdentifierCommands,
)
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
from request_engine.modules.tenancy.adapters.db.party_rollback_commands import (
    PostgresPartyRollbackCommands,
)


class PostgresPartyRegistryCommands(
    PostgresPartyRegistrationCommands,
    PostgresPartyContactPointCommands,
    PostgresPartyContactPointConfirmationCommands,
    PostgresPartyAdministrativeIdentifierCommands,
    PostgresPartyCorrectionCommands,
    PostgresPartyDeactivationCommands,
    PostgresPartyRollbackCommands,
):
    """Tenancy-owned idempotent party registry commands.

    Composition of the per-capability command adapters: registration, contact
    points, administrative identifiers, operator-granted corrections,
    deactivation and identity rollback. Each mutation owns one Session, one
    explicit tenant transaction, standard idempotency replay and typed
    conflict mapping.
    """
