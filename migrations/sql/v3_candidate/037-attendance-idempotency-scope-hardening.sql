BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, request_cmd, pg_catalog;

-- Attendance historically used payload-dependent idempotency scopes
-- (appointments.attendance.accepted/declined) even though both values are the
-- same semantic command. That permits one Idempotency-Key to identify two
-- commands when only the response payload changes. Normalize that legacy split
-- to the stable command scope already used by the command fingerprint.
DO $migration$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM request_engine.idempotency_records
        WHERE capability IN (
            'appointments.attendance.accepted',
            'appointments.attendance.declined',
            'booking.record_attendance_response'
        )
        GROUP BY organization_id, principal_id, idempotency_key
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION
            'attendance idempotency scope migration found conflicting historical keys'
            USING ERRCODE = 'P1001';
    END IF;
END
$migration$;

UPDATE request_engine.idempotency_records
SET capability = 'booking.record_attendance_response'
WHERE capability IN (
    'appointments.attendance.accepted',
    'appointments.attendance.declined'
);

CREATE OR REPLACE FUNCTION request_cmd.acquire_idempotency(
    p_organization_id uuid,
    p_principal_id uuid,
    p_capability text,
    p_idempotency_key text,
    p_request_fingerprint text
)
RETURNS TABLE (
    idempotency_id uuid,
    status text,
    result_data jsonb,
    replay boolean
)
LANGUAGE plpgsql
AS $function$
DECLARE
    v_record request_engine.idempotency_records%ROWTYPE;
    v_capability text;
BEGIN
    IF p_organization_id IS DISTINCT FROM request_engine.current_organization_id() THEN
        RAISE EXCEPTION 'organization context mismatch'
            USING ERRCODE = '42501';
    END IF;

    v_capability := CASE p_capability
        WHEN 'appointments.attendance.accepted'
            THEN 'booking.record_attendance_response'
        WHEN 'appointments.attendance.declined'
            THEN 'booking.record_attendance_response'
        ELSE p_capability
    END;

    INSERT INTO request_engine.idempotency_records (
        organization_id,
        principal_id,
        capability,
        idempotency_key,
        request_fingerprint
    )
    VALUES (
        p_organization_id,
        p_principal_id,
        v_capability,
        p_idempotency_key,
        p_request_fingerprint
    )
    ON CONFLICT (organization_id, principal_id, capability, idempotency_key)
    DO NOTHING;

    SELECT *
      INTO v_record
      FROM request_engine.idempotency_records i
     WHERE i.organization_id = p_organization_id
       AND i.principal_id = p_principal_id
       AND i.capability = v_capability
       AND i.idempotency_key = p_idempotency_key
     FOR UPDATE;

    IF v_record.request_fingerprint <> p_request_fingerprint THEN
        RAISE EXCEPTION 'idempotency key reused with different request fingerprint'
            USING ERRCODE = 'P1001';
    END IF;

    RETURN QUERY SELECT
        v_record.id,
        v_record.status,
        v_record.result_data,
        v_record.status = 'completed';
END
$function$;

RESET search_path;
RESET ROLE;
COMMIT;
