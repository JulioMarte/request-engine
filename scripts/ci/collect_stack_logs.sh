#!/usr/bin/env bash
set -uo pipefail
root="${1:-.ci/docker-e2e}"
services_dir="$root/services"; docker_dir="$root/docker"
mkdir -p "$services_dir" "$docker_dir" "$root/phases"
compose=(docker compose -f deploy/reference/compose.e2e.yaml)
"${compose[@]}" ps -a >"$docker_dir/compose-ps.txt" 2>&1 || true
"${compose[@]}" config >"$docker_dir/compose-config.txt" 2>&1 || true
ids="$(${compose[@]} ps -aq 2>/dev/null || true)"
[[ -z "$ids" ]] || docker inspect $ids >"$docker_dir/inspect.json" 2>&1 || true
while IFS= read -r service; do
  [[ -z "$service" ]] && continue
  "${compose[@]}" logs --no-color --timestamps "$service" >"$services_dir/$service.log" 2>&1 || true
done < <("${compose[@]}" config --services 2>/dev/null || true)
python - "$root" <<'PY'
import json, os, pathlib, subprocess, sys
root=pathlib.Path(sys.argv[1])
data={k.lower():os.getenv(k) for k in ('GITHUB_REPOSITORY','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_WORKFLOW','GITHUB_JOB','GITHUB_EVENT_NAME','GITHUB_REF','GITHUB_SHA','RUNNER_OS')}
try: data['docker_version']=subprocess.check_output(['docker','--version'],text=True).strip()
except Exception: data['docker_version']=None
(root/'metadata.json').write_text(json.dumps(data,indent=2)+'\n')
PY
cat >"$root/EVIDENCE_SCOPE.txt" <<'EOF'
CI PLUMBING EVIDENCE ONLY.
Vault dev mode and the SMTP catcher do not certify production secret handling or email deliverability.
External TLS/ingress, production-shaped backup/restore and restore-fencing, human break-glass, RPO/RTO, and SLOs remain outside this CI evidence.
Never treat a green Docker E2E run as certification of those production properties.
EOF
find "$root" -type f \( -name '*.log' -o -name '*.txt' \) -print0 | while IFS= read -r -d '' file; do
  sed -E -i -e 's/(Authorization:[[:space:]]*Bearer[[:space:]]+)[^[:space:]]+/\1[REDACTED]/Ig' -e 's/(ONE-TIME BOOTSTRAP TOKEN:[[:space:]]*).*/\1[REDACTED]/Ig' "$file" || true
done
