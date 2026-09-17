#!/usr/bin/env bash
set -euo pipefail

requested="${1:-smoke}"
registry="scripts/ci/e2e_suite_registry.py"
compose_file="deploy/reference/compose.e2e.yaml"
artifact_root="${E2E_ARTIFACT_ROOT:-.ci/docker-e2e}"

build_images() {
  docker compose -f "$compose_file" --profile runner build api e2e-runner
}

[[ "$requested" != "all" ]] || {
  echo "run_e2e_suite.sh executes exactly one suite; use run_e2e_platform.sh all" >&2
  exit 2
}

spec_json="$(python "$registry" resolve "$requested")"
readarray -t resolved < <(python - "$spec_json" <<'PY'
import json, sys
spec=json.loads(sys.argv[1])
print(spec["selector"])
print(spec["artifact_namespace"])
for profile in spec.get("profiles", []):
    print(f"profile:{profile}")
for service in spec.get("services", []):
    print(f"service:{service}")
PY
)
selector="${resolved[0]}"
namespace="${resolved[1]}"
profiles=()
runtime_services=()
for item in "${resolved[@]:2}"; do
  case "$item" in
    profile:*) profiles+=("${item#profile:}") ;;
    service:*) runtime_services+=("${item#service:}") ;;
  esac
done
((${#runtime_services[@]} > 0)) || {
  echo "suite '$requested' declares no runtime services" >&2
  exit 2
}

safe_suite="$(printf '%s' "$requested" | tr -c 'a-zA-Z0-9_.-' '-')"
run_suffix="${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}"
export COMPOSE_PROJECT_NAME="re-e2e-${safe_suite}-${run_suffix}"
export E2E_RUNNER_IMAGE_TAG="${E2E_RUNNER_IMAGE_TAG:-${REQUEST_ENGINE_IMAGE_TAG:-e2e}}"

compose=(docker compose -f "$compose_file" --profile runner)
for profile in "${profiles[@]}"; do
  compose+=(--profile "$profile")
done

suite_artifacts="$artifact_root/$namespace"
mkdir -p "$suite_artifacts/phases"
chmod 0777 "$suite_artifacts"

cleanup() {
  status=$?
  bash scripts/ci/collect_stack_logs.sh "$suite_artifacts" || true
  if [[ "${E2E_KEEP_STACK:-0}" != "1" ]]; then
    "${compose[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  fi
  exit "$status"
}
trap cleanup EXIT

if [[ "${E2E_IMAGES_READY:-0}" != "1" ]]; then
  build_images 2>&1 | tee "$suite_artifacts/phases/build.log"
fi

infra=(postgres)
for profile in "${profiles[@]}"; do
  case "$profile" in
    secrets) infra+=(vault) ;;
    delivery) infra+=(mailpit) ;;
  esac
done
"${compose[@]}" up -d "${infra[@]}" 2>&1 | tee "$suite_artifacts/phases/infrastructure.log"

{
  "${compose[@]}" run --rm --no-deps migrate
  "${compose[@]}" exec -T -e PGPASSWORD=ci-postgres-only postgres \
    psql -U postgres -d request_engine < deploy/reference/init-runtime-roles.sql
} 2>&1 | tee "$suite_artifacts/phases/migrate.log"

exec > >(tee -a "$suite_artifacts/phases/bootstrap.log") 2>&1
bootstrap_dsn='postgresql://postgres:ci-postgres-only@postgres:5432/request_engine'
issue="$("${compose[@]}" run --rm --no-deps -e REQUEST_ENGINE_BOOTSTRAP_DSN="$bootstrap_dsn" api request-engine-platform-bootstrap issue --provenance "e2e:${GITHUB_RUN_ID:-local}:$requested")"
authority="$(printf '%s\n' "$issue" | sed -n 's/^Native authority: //p')"
token="$(printf '%s\n' "$issue" | sed -n 's/^ONE-TIME BOOTSTRAP TOKEN: //p')"
test -n "$authority" && test -n "$token"
password="$(openssl rand -base64 36)Aa1!"
printf '%s\n%s\n%s\n' "$token" "$password" "$password" | \
  "${compose[@]}" run --rm --no-deps -T -e REQUEST_ENGINE_BOOTSTRAP_DSN="$bootstrap_dsn" api \
    request-engine-platform-bootstrap establish --login "ci-platform-controller-$safe_suite"
export REQUEST_ENGINE_NATIVE_IDENTITY_AUTHORITY_ID="$authority"
echo 'bootstrap completed; sensitive material intentionally omitted'

"${compose[@]}" up -d --no-build --wait --wait-timeout "${STACK_READY_TIMEOUT_SECONDS:-180}" \
  "${runtime_services[@]}" 2>&1 | tee "$suite_artifacts/phases/runtime-start.log"

export E2E_RUNTIME_SERVICES="${runtime_services[*]}"
bash scripts/ci/assert_reference_image_identity.sh 2>&1 | tee "$suite_artifacts/phases/image-identity.log"

artifact_abs="$(cd "$suite_artifacts" && pwd)"
"${compose[@]}" run --rm --no-deps \
  --user "$(id -u):$(id -g)" \
  -v "$artifact_abs:/artifacts" \
  e2e-runner run "$selector" --artifact-dir /artifacts \
  2>&1 | tee "$suite_artifacts/phases/runner.log"

echo "E2E suite '$requested' passed"
