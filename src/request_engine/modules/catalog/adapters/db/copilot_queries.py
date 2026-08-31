OFFERING_QUERY = """
SELECT id AS offering_id, display_name
FROM request_engine.offerings
WHERE organization_id=:organization_id
  AND (lower(btrim(display_name))=lower(btrim(:reference))
       OR lower(btrim(offering_key))=lower(btrim(:reference)))
ORDER BY id
"""

LOCATION_QUERY = """
WITH clock AS (SELECT clock_timestamp() AS observed_at)
SELECT l.id AS location_id,l.display_name,l.timezone,clock.observed_at,l.operational_revision,
       (((clock.observed_at AT TIME ZONE l.timezone)::date + max(h.local_end))
         AT TIME ZONE l.timezone) AS operational_day_end_at
FROM request_engine.locations l
CROSS JOIN clock
LEFT JOIN request_engine.location_operational_hours h
  ON h.organization_id=l.organization_id AND h.location_id=l.id
 AND h.weekday=extract(isodow FROM clock.observed_at AT TIME ZONE l.timezone)::int - 1
 AND h.active
 AND (h.valid_from IS NULL
      OR h.valid_from <= (clock.observed_at AT TIME ZONE l.timezone)::date)
 AND (h.valid_until IS NULL
      OR h.valid_until >= (clock.observed_at AT TIME ZONE l.timezone)::date)
WHERE l.organization_id=:organization_id AND l.id=:location_id
GROUP BY l.id,l.display_name,l.timezone,clock.observed_at,l.operational_revision
"""
