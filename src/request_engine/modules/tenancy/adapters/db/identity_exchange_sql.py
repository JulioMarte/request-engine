"""SQL calls for the narrow S0d SECURITY DEFINER identity-exchange bridge."""

from sqlalchemy import text

LOCAL_CEDULA = text(
    """
    SELECT d.normalized_value
    FROM request_engine.party_identity_documents d
    JOIN request_engine.parties p
      ON p.organization_id = d.organization_id AND p.id = d.party_id AND p.active
    WHERE d.organization_id = :organization_id AND d.party_id = :party_id
      AND d.kind = 'cedula' AND d.active
    LIMIT 1
    """
)

PUBLISH = text(
    "SELECT request_engine.publish_portable_person_v1("
    ":party_id, :fingerprint, :consented_fields, :principal_id)"
)

CREATE_CANDIDATE = text(
    "SELECT request_engine.create_identity_exchange_candidate_v1("
    ":fingerprint, :principal_id)"
)

CONSUME_CANDIDATE = text(
    """
    SELECT portable_person_id, profile
    FROM request_engine.consume_identity_exchange_candidate_v1(
        :candidate_ref, :fingerprint, :principal_id
    )
    """
)

BIND_CANDIDATE = text(
    "SELECT request_engine.bind_consumed_identity_candidate_v1("
    ":candidate_ref, :party_id, :consented_fields, :principal_id)"
)
