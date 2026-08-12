from dataclasses import dataclass
from uuid import UUID

BOOK_APPOINTMENT_SCOPE = "appointments.book"
MANAGE_APPOINTMENT_SCOPE = "appointments.manage"
SUBJECT_OVERRIDE_PERMISSION = "appointments.subject_override"


@dataclass(frozen=True, slots=True)
class SubjectAuthorityRequirement:
    """Authority policy carried into the authoritative booking transaction.

    ``allow_operator_override`` is materialized only from an authenticated
    actor's operator permission at an entrypoint. When false, the transaction
    must resolve a current exact-scope Representation for the Principal and
    subject Party before it may mutate booking state.
    """

    subject_party_id: UUID
    scope_key: str
    allow_operator_override: bool = False
