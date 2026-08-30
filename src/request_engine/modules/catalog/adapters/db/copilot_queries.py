RESOURCE_QUERY = """
WITH clock AS (SELECT clock_timestamp() AS observed_at)
SELECT r.id AS resource_id, a.location_id, a.id AS assignment_id, l.timezone,
       clock.observed_at, l.operational_revision AS location_operational_revision,
       r.availability_revision AS resource_availability_revision,
       (((clock.observed_at AT TIME ZONE l.timezone)::date + max(rla.local_end))
         AT TIME ZONE l.timezone) AS scheduled_end_at
FROM request_engine.resources r
JOIN request_engine.resource_location_assignments a
  ON a.organization_id=r.organization_id AND a.resource_id=r.id
JOIN request_engine.locations l
  ON l.organization_id=a.organization_id AND l.id=a.location_id
CROSS JOIN clock
LEFT JOIN request_engine.resource_location_availability rla
  ON rla.organization_id=a.organization_id
 AND rla.resource_location_assignment_id=a.id
 AND rla.weekday=extract(isodow FROM clock.observed_at AT TIME ZONE l.timezone)::int - 1
WHERE r.organization_id=:organization_id AND a.effective_during @> clock.observed_at
  AND (lower(btrim(r.display_name))=lower(btrim(:reference))
       OR lower(btrim(r.resource_key))=lower(btrim(:reference)))
GROUP BY r.id,a.location_id,a.id,l.timezone,clock.observed_at,l.operational_revision,
         r.availability_revision
ORDER BY r.id,a.id
"""

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
SELECT l.id AS location_id,l.timezone,clock.observed_at,l.operational_revision,
       (((clock.observed_at AT TIME ZONE l.timezone)::date + max(h.local_end))
         AT TIME ZONE l.timezone) AS operational_day_end_at
FROM request_engine.locations l
CROSS JOIN clock
LEFT JOIN request_engine.location_operational_hours h
  ON h.organization_id=l.organization_id AND h.location_id=l.id
 AND h.weekday=extract(isodow FROM clock.observed_at AT TIME ZONE l.timezone)::int - 1
WHERE l.organization_id=:organization_id AND l.id=:location_id
GROUP BY l.id,l.timezone,clock.observed_at,l.operational_revision
"""
