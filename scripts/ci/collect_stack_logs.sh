#!/usr/bin/env bash
set -uo pipefail
out="${1:-.ci/docker-e2e/logs}"; mkdir -p "$out"
compose=(docker compose -f deploy/reference/compose.e2e.yaml)
"${compose[@]}" ps -a >"$out/compose-ps.txt" 2>&1 || true
"${compose[@]}" logs --no-color --timestamps >"$out/compose.log" 2>&1 || true
ids="$(${compose[@]} ps -aq 2>/dev/null || true)"; [[ -z "$ids" ]] || docker inspect $ids >"$out/docker-inspect.json" 2>&1 || true
cat >"$out/EVIDENCE_SCOPE.txt" <<'EOF'
CI plumbing evidence only. Vault dev mode and the SMTP catcher do not certify production secret handling or email deliverability.
External TLS/ingress, production-shaped backup/restore and restore-fencing, human break-glass, RPO/RTO, and SLOs remain outside this CI evidence.
EOF
