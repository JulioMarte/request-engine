RESOURCE_QUERY = """
WITH clock AS (SELECT clock_timestamp() AS observed_at)
SELECT r.id AS resource_id,
       r.display_name,
       a.location_id,
       a.id AS assignment_id,
       r.availability_revision AS resource_availability_revision
FROM request_engine.resources r
JOIN request_engine.resource_location_assignments a
  ON a.organization_id=r.organization_id AND a.resource_id=r.id
CROSS JOIN clock
WHERE r.organization_id=:organization_id
  AND a.effective_during @> clock.observed_at
  AND (
    lower(btrim(r.display_name))=lower(btrim(:reference))
    OR lower(btrim(r.resource_key))=lower(btrim(:reference))
  )
ORDER BY r.id,a.id
"""

ASSIGNMENT_DAY_END_QUERY = """
SELECT max(local_end) AS scheduled_local_end
FROM request_engine.resource_location_availability
WHERE organization_id=:organization_id
  AND resource_location_assignment_id=:assignment_id
  AND weekday=:weekday
"""
