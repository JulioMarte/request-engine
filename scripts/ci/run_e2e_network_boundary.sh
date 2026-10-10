#!/usr/bin/env bash
# Specialized infrastructure driver: probes have no Docker/DB authority.
set -euo pipefail
: "${E2E_NETWORK_PLAN_DIR:?}" "${E2E_NETWORK_ARTIFACT_DIR:?}" "${E2E_TLS_DIR:?}"
compose=(docker compose -f deploy/reference/compose.e2e.yaml -f deploy/reference/compose.lab-tls.yaml)
container_ip() {
  local cid
  cid="$("${compose[@]}" ps -q "$1")"
  [[ -n "$cid" ]] || { echo "missing $1 container" >&2; return 1; }
  docker inspect "$cid" --format "{{with index .NetworkSettings.Networks \"${COMPOSE_PROJECT_NAME}_$2\"}}{{.IPAddress}}{{end}}"
}
postgres_ip="$(container_ip postgres backend)"
bao_ip="$(container_ip openbao backend)"
control_ip="$(container_ip control-ingress private-ingress)"
control_backend_ip="$(container_ip control-plane backend)"
python - "$E2E_NETWORK_PLAN_DIR" "$postgres_ip" "$bao_ip" "$control_ip" "$control_backend_ip" <<'PY'
import ipaddress, json, pathlib, sys
root=pathlib.Path(sys.argv[1])
endpoints=[]
for label,address,port in zip(('postgres','openbao','control-ingress','control-runtime'),sys.argv[2:],(5432,8200,443,8001),strict=True):
    if ipaddress.ip_address(address).version != 4: raise SystemExit('lab requires actual IPv4 addresses')
    endpoints.append(dict(id=label,address=address,port=port))
common=dict(schema='request-engine/network-auth-plan/v1',timeout_seconds=3)
plans={
 'private': dict(common,role='private',control_origin='https://control-lab',reachable_endpoints=endpoints),
 'public': dict(common,role='public',api_origin='https://api-lab',blocked_endpoints=endpoints),
 'admission-before': dict(common,role='admission',targets=dict(api='https://api-lab',replica='https://api-replica-lab'),requests=[dict(target=t,expected_status=200) for t in ('api','replica','api')]),
 'admission-after': dict(common,role='admission',targets=dict(api='https://api-lab',replica='https://api-replica-lab'),requests=[dict(target=t,expected_status=429) for t in ('replica','api')]),
}
for name,plan in plans.items(): (root/f'{name}.json').write_text(json.dumps(plan)+'\n')
PY
probe() {
  local service="$1" plan="$2"
  local baseline=()
  if [[ "$plan" == public ]]; then baseline=(--private-baseline /artifacts/private.json); fi
  "${compose[@]}" run --rm --no-deps --user "$(id -u):$(id -g)" \
    --entrypoint python \
    -v "$E2E_NETWORK_PLAN_DIR:/plans:ro" \
    -v "$E2E_TLS_DIR/ca.crt:/tls/ca.crt:ro" \
    -v "$E2E_NETWORK_ARTIFACT_DIR:/artifacts" \
    "$service" /e2e/network_boundary_probe.py "/plans/$plan.json" \
    --ca-file /tls/ca.crt --output "/artifacts/$plan.json" "${baseline[@]}"
}
# A live private listener is mandatory before a public refusal can count.
probe private-probe private
probe public-probe public
started="$SECONDS"
probe public-probe admission-before
"${compose[@]}" restart api-replica
"${compose[@]}" up -d --no-build --wait --wait-timeout 30 api-replica
probe public-probe admission-after
((SECONDS-started < 55)) || { echo 'admission test exceeded its 60s window safety margin' >&2; exit 1; }
# Independent authoritative-state oracle stays in the outer administrator.
state="$("${compose[@]}" exec -T -e PGPASSWORD=ci-postgres-only postgres \
  psql -tA -v ON_ERROR_STOP=1 -U postgres -d request_engine -c \
  "SELECT json_build_object('configured_limit',configured_limit,'accepted_attempts',cardinality(attempts),'challenges',(SELECT count(*) FROM request_engine.webauthn_challenges),'sessions',(SELECT count(*) FROM request_engine.native_sessions)) FROM request_engine.http_auth_admission_state WHERE singleton")"
python - "$state" "$E2E_NETWORK_ARTIFACT_DIR/admission-state.json" <<'PY'
import json,pathlib,sys
actual=json.loads(sys.argv[1])
expected=dict(configured_limit=3,accepted_attempts=3,challenges=0,sessions=0)
if actual != expected: raise SystemExit(f'authoritative admission oracle failed: {actual}')
pathlib.Path(sys.argv[2]).write_text(json.dumps(dict(actual,replica_restart_survived=True,production_certified=False),indent=2)+'\n')
PY
