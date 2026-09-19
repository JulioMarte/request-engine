#!/usr/bin/env bash
set -uo pipefail
root="${1:-.ci/docker-e2e}"
services_dir="$root/services"; docker_dir="$root/docker"
mkdir -p "$services_dir" "$docker_dir" "$root/phases"
compose=(docker compose -f deploy/reference/compose.e2e.yaml --profile runner --profile worker --profile secrets --profile delivery)

"${compose[@]}" ps -a >"$docker_dir/compose-ps.txt" 2>&1 || true
"${compose[@]}" config --services >"$docker_dir/compose-services.txt" 2>&1 || true
"${compose[@]}" config --images >"$docker_dir/compose-images.txt" 2>&1 || true

docker version --format '{{json .}}' >"$docker_dir/docker-version.json" 2>&1 || true
docker compose version >"$docker_dir/compose-version.txt" 2>&1 || true

ids="$(${compose[@]} ps -aq 2>/dev/null || true)"
if [[ -n "$ids" ]]; then
  docker inspect $ids | python -c '
import json, sys
raw=json.load(sys.stdin)
safe=[]
for item in raw:
    networks={name:{"IPAddress": value.get("IPAddress"), "Aliases": value.get("Aliases")} for name,value in item.get("NetworkSettings",{}).get("Networks",{}).items()}
    state=item.get("State",{})
    safe.append({
        "Name": item.get("Name"),
        "Image": item.get("Image"),
        "RestartCount": item.get("RestartCount"),
        "State": {key: state.get(key) for key in ("Status","Running","ExitCode","OOMKilled","Error","StartedAt","FinishedAt","Health") if key in state},
        "Networks": networks,
        "Mounts": [{"Type": m.get("Type"), "Destination": m.get("Destination")} for m in item.get("Mounts",[])],
    })
json.dump(safe, sys.stdout, indent=2)
print()
' >"$docker_dir/container-state.json" 2>&1 || true
fi

while IFS= read -r service; do
  [[ -z "$service" ]] && continue
  "${compose[@]}" logs --no-color --timestamps "$service" >"$services_dir/$service.log" 2>&1 || true
done < <("${compose[@]}" config --services 2>/dev/null || true)

python - "$root" <<'PY'
import json, os, pathlib, subprocess, sys
root=pathlib.Path(sys.argv[1])
data={k.lower():os.getenv(k) for k in ('GITHUB_REPOSITORY','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_WORKFLOW','GITHUB_JOB','GITHUB_EVENT_NAME','GITHUB_REF','GITHUB_SHA','RUNNER_OS','COMPOSE_PROJECT_NAME')}
try: data['docker_version']=subprocess.check_output(['docker','--version'],text=True).strip()
except Exception: data['docker_version']=None
(root/'metadata.json').write_text(json.dumps(data,indent=2)+'\n')
PY

cat >"$root/EVIDENCE_SCOPE.txt" <<'EOF'
SYSTEM/E2E EVIDENCE FOR THE SELECTED SUITE ONLY.
Vault dev mode and Mailpit do not certify production secret handling or email deliverability.
External TLS/ingress, production-shaped backup/restore and restore-fencing, human break-glass, RPO/RTO, and SLOs remain outside this CI evidence.
Raw Compose configuration and raw Docker inspect output are intentionally excluded because they may contain credentials.
EOF

find "$root" -type f \( -name '*.log' -o -name '*.txt' -o -name '*.json' \) -print0 | while IFS= read -r -d '' file; do
  sed -E -i \
    -e 's/(Authorization:[[:space:]]*Bearer[[:space:]]+)[^[:space:]]+/\1[REDACTED]/Ig' \
    -e 's/(ONE-TIME BOOTSTRAP TOKEN:[[:space:]]*).*/\1[REDACTED]/Ig' \
    -e 's#(postgres(ql)?(\+psycopg)?://[^:/[:space:]]+:)[^@/[:space:]]+@#\1[REDACTED]@#Ig' \
    -e 's/(VAULT_TOKEN[=:][[:space:]]*)[^[:space:]]+/\1[REDACTED]/Ig' \
    "$file" || true
done
