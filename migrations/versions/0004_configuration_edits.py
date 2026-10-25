"""Owner configuration edits after creation (rename, replace, deactivate).

Product need: an owner configuring a small business from the app must be able to
rename an Offering, supersede its duration/price, replace which services a
Resource provides and remove a saved Resource-wide absence. Location rename,
Location hours-exception deactivation, holiday removal and ServiceQueue
deactivation need no DDL (``locations.display_name``,
``location_hours_exceptions.active`` and ``service_queues.active``/``revision``
already exist).

Change (expand-only):

* ``request_engine.offerings`` gains ``revision bigint NOT NULL DEFAULT 1``
  (CHECK > 0) stepped by the existing ``guard_exact_revision_step`` trigger, so the
  Catalog command ``catalog_offering_update`` can compare-and-set the
  Offering-level label. Existing rows start at revision 1;
* ``request_engine.schedule_exceptions`` (Resource-wide exceptions) gains
  ``active boolean NOT NULL DEFAULT true`` and ``updated_at`` (+ the standard
  ``touch_updated_at`` trigger), mirroring
  ``resource_location_schedule_exceptions``. A removed absence is a deactivated,
  still-auditable row instead of a deleted one. The existing
  ``schedule_exceptions_bump_resource`` trigger already advances
  ``resources.availability_revision`` on UPDATE;
* ``request_engine_app`` gains ``DELETE`` on
  ``request_engine.resource_capability_assignments`` so
  ``booking_resource_capabilities_replace`` can remove a link row. The link is
  configuration (which ResourceCapability a Resource satisfies), not a business
  fact; every replacement is recorded in the audit log with the previous and new
  capability sets.

Schema-change checklist (migrations/AGENTS.md):

* Business owners: Catalog (Offering), Booking (Resource, ScheduleException,
  resource capability assignment).
* Guarantees: tenant Organization equality/RLS (unchanged policies), explicit
  authority (owner commands keep exact Party authority), capacity serialization
  (Resource remains the root; ``guard_capacity_claim`` keeps requiring the
  capability link for every *new or re-validated* active claim), immutable
  OfferingVersion history (no UPDATE grant is added to versions/terms/
  requirements), idempotency and transaction atomicity.
* Change class: CONTROLLED additive. Columns with constant/volatile defaults, one
  CHECK, two triggers and one grant. No backfill UPDATE (an UPDATE would fire the
  availability/recovery revision triggers); existing exception rows receive
  ``active = true`` and ``updated_at`` = migration time.
* READ/PLAN/LOCK/VALIDATE/WRITE/EMIT: owned by the Python commands. Capability
  replacement locks the Resource ``FOR UPDATE`` (same root as
  ``guard_capacity_claim``), refuses while a live Hold depends on a removed
  capability, never touches existing CapacityClaims and advances
  ``availability_revision`` exactly once.
* Tenant/RLS/roles: no new table or policy; ``request_engine_admin`` already holds
  ALL. ``request_engine_app`` gets only the one DELETE grant above.
* Failure/concurrency: unchanged constraints; offering label CAS uses the stepped
  ``revision``; concurrent losers receive the owner revision conflict.
* Roll-forward: downgrade is refused (deactivation history and revisions are
  durable state).
* Falsification: tests/e2e/test_configuration_edits_catalog.py,
  tests/e2e/test_configuration_edits_booking.py,
  tests/e2e/test_configuration_edits_queue.py and the runtime privilege
  inventory (tests/db/runtime_table_contract.py).
"""

from alembic import op

revision: str = "0004_configuration_edits"
down_revision: str | None = "0003_tenant_controller_v10"
branch_labels: str | None = None
depends_on: str | None = None

_OFFERING_REVISION = """
ALTER TABLE request_engine.offerings
    ADD COLUMN revision bigint DEFAULT 1 NOT NULL;
ALTER TABLE request_engine.offerings
    ADD CONSTRAINT offerings_revision_check CHECK (revision > 0);
CREATE TRIGGER offerings_revision_step
    BEFORE UPDATE ON request_engine.offerings
    FOR EACH ROW EXECUTE FUNCTION request_engine.guard_exact_revision_step();
"""

_RESOURCE_EXCEPTION_ACTIVE = """
ALTER TABLE request_engine.schedule_exceptions
    ADD COLUMN active boolean DEFAULT true NOT NULL;
ALTER TABLE request_engine.schedule_exceptions
    ADD COLUMN updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL;
CREATE TRIGGER schedule_exceptions_touch
    BEFORE UPDATE ON request_engine.schedule_exceptions
    FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
"""

_CAPABILITY_ASSIGNMENT_DELETE = """
GRANT DELETE ON TABLE request_engine.resource_capability_assignments TO request_engine_app;
"""


def upgrade() -> None:
    op.execute(_OFFERING_REVISION)
    op.execute(_RESOURCE_EXCEPTION_ACTIVE)
    op.execute(_CAPABILITY_ASSIGNMENT_DELETE)


def downgrade() -> None:
    raise RuntimeError("configuration revisions and deactivation history are durable; roll forward")
