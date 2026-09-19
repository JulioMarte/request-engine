#!/usr/bin/env bash
set -euo pipefail

requested="${1:-smoke}"
registry="scripts/ci/e2e_suite_registry.py"
compose_file="deploy/reference/compose.e2e.yaml"
artifact_root="${E2E_ARTIFACT_ROOT:-.ci/docker-e2e}"

retry_docker() {
  log_file="$1"
  shift
  bash scripts/ci/retry_transient_docker.sh "$log_file" "$@"
}

build_images() {
  retry_docker "$suite_artifacts/phases/build.log" \
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
for profile in spec.get("profiles", []): print(f"profile:{profile}")
for service in spec.get("services", []): print(f"service:{service}")
for service in spec.get("deferred_services", []): print(f"deferred:{service}")
for mapping in spec.get("runtime_env_from_state", []): print(f"runtimeenv:{mapping}")
for fault in spec.get("faults", []): print(f"fault:{fault}")
PY
)
selector="${resolved[0]}"
namespace="${resolved[1]}"
profiles=()
runtime_services=()
deferred_services=()
runtime_env_from_state=()
faults=()
for item in "${resolved[@]:2}"; do
  case "$item" in
    profile:*) profiles+=("${item#profile:}") ;;
    service:*) runtime_services+=("${item#service:}") ;;
    deferred:*) deferred_services+=("${item#deferred:}") ;;
    runtimeenv:*) runtime_env_from_state+=("${item#runtimeenv:}") ;;
    fault:*) faults+=("${item#fault:}") ;;
  esac
done
((${#runtime_services[@]} > 0)) || { echo "suite '$requested' declares no runtime services" >&2; exit 2; }

initial_services=()
for service in "${runtime_services[@]}"; do
  deferred=0
  for item in "${deferred_services[@]}"; do [[ "$service" == "$item" ]] && deferred=1; done
  ((deferred == 1)) || initial_services+=("$service")
done

safe_suite="$(printf '%s' "$requested" | tr -c 'a-zA-Z0-9_.-' '-')"
run_suffix="${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}"
export COMPOSE_PROJECT_NAME="re-e2e-${safe_suite}-${run_suffix}"
export E2E_RUNNER_IMAGE_TAG="${E2E_RUNNER_IMAGE_TAG:-${REQUEST_ENGINE_IMAGE_TAG:-e2e}}"
export E2E_COMPOSE_FILE="$compose_file"
export E2E_COMPOSE_PROFILES="$(IFS=,; echo "${profiles[*]}")"

compose=(docker compose -f "$compose_file" --profile runner)
for profile in "${profiles[@]}"; do compose+=(--profile "$profile"); done

suite_artifacts="$artifact_root/$namespace"
mkdir -p "$suite_artifacts/phases" && chmod 0777 "$suite_artifacts"
handoff_parent="${RUNNER_TEMP:-/tmp}"
state_dir="$(mktemp -d "$handoff_parent/request-engine-e2e-state.XXXXXX")"
secret_dir="$(mktemp -d "$handoff_parent/request-engine-e2e-secrets.XXXXXX")"
chmod 0700 "$state_dir" "$secret_dir"

cleanup() {
  status=$?
  bash scripts/ci/collect_stack_logs.sh "$suite_artifacts" || true
  if [[ "${E2E_KEEP_STACK:-0}" != "1" ]]; then "${compose[@]}" down -v --remove-orphans >/dev/null 2>&1 || true; fi
  rm -rf "$state_dir" "$secret_dir"
  exit "$status"
}
trap cleanup EXIT

if [[ "${E2E_IMAGES_READY:-0}" != "1" ]]; then build_images; fi

infra=(postgres)
for profile in "${profiles[@]}"; do
  case "$profile" in
    secrets) infra+=(openbao) ;;
    delivery) infra+=(mailpit) ;;
    worker) infra+=(event-sink) ;;
  esac
done
retry_docker "$suite_artifacts/phases/infrastructure.log" \
  "${compose[@]}" up -d --wait --wait-timeout "${INFRA_READY_TIMEOUT_SECONDS:-120}" "${infra[@]}"

for profile in "${profiles[@]}"; do
  case "$profile" in
    secrets)
      export REQUEST_ENGINE_OPENBAO_ADDR="http://openbao:8200"
      export REQUEST_ENGINE_OPENBAO_TOKEN="ci-root-token"
      ;;
    delivery)
      export REQUEST_ENGINE_SMTP_HOST="mailpit"
      export REQUEST_ENGINE_SMTP_PORT="1025"
      export REQUEST_ENGINE_SMTP_SENDER="recovery@example.test"
      export REQUEST_ENGINE_SMTP_STARTTLS="false"
      export REQUEST_ENGINE_SMTP_SSL="false"
      ;;
  esac
done

{
  "${compose[@]}" run --rm --no-deps migrate
  "${compose[@]}" exec -T -e PGPASSWORD=ci-postgres-only postgres \
    psql -U postgres -d request_engine < deploy/reference/init-runtime-roles.sql
} 2>&1 | tee "$suite_artifacts/phases/migrate.log"

login_handle="ci-platform-controller-$safe_suite"
password="$(openssl rand -base64 36)Aa1!"
if [[ "${GITHUB_ACTIONS:-false}" == "true" ]]; then echo "::add-mask::$password"; fi

# The clean-install trust root is the built-in native authority bound to the
# instance by migration. Read it for process startup. The runner learns both
# built-in authority ids from the HTTP claim receipt, so no bootstrap.json or
# bootstrap CLI is involved in the clean-install journey.
authority="$("${compose[@]}" exec -T -e PGPASSWORD=ci-postgres-only postgres psql -tA -U postgres -d request_engine -c 'SELECT built_in_native_authority_id FROM request_engine.platform_instance WHERE singleton_key = 1')"
test -n "$authority"
export REQUEST_ENGINE_NATIVE_IDENTITY_AUTHORITY_ID="$authority"

python - "$secret_dir/platform-controller.json" "$login_handle" "$password" <<'PY'
import json, os, pathlib, sys
path=pathlib.Path(sys.argv[1]); path.write_text(json.dumps({"login_handle":sys.argv[2],"password":sys.argv[3]},sort_keys=True)+"\n",encoding="utf-8"); os.chmod(path,0o600)
PY

if ((${#initial_services[@]} > 0)); then
  "${compose[@]}" up -d --no-build --wait --wait-timeout "${STACK_READY_TIMEOUT_SECONDS:-180}" \
    "${initial_services[@]}" 2>&1 | tee "$suite_artifacts/phases/runtime-start.log"
fi

artifact_abs="$(cd "$suite_artifacts" && pwd)"
state_abs="$(cd "$state_dir" && pwd)"
secret_abs="$(cd "$secret_dir" && pwd)"
run_runner() {
  phase="$1"; phase_artifacts="$artifact_abs"
  if [[ "$phase" != "main" ]]; then phase_artifacts="$artifact_abs/$phase"; mkdir -p "$phase_artifacts"; chmod 0777 "$phase_artifacts"; fi
  "${compose[@]}" run --rm --no-deps --user "$(id -u):$(id -g)" \
    -e E2E_STATE_DIR=/state -e E2E_SECRET_DIR=/secrets \
    -v "$phase_artifacts:/artifacts" -v "$state_abs:/state" -v "$secret_abs:/secrets:ro" \
    e2e-runner run "$selector" --phase "$phase" --artifact-dir /artifacts
}

if ((${#deferred_services[@]} > 0)); then
  run_runner prepare-worker 2>&1 | tee "$suite_artifacts/phases/runner-prepare-runtime.log"
  for mapping in "${runtime_env_from_state[@]}"; do
    variable="${mapping%%=*}"; source_ref="${mapping#*=}"; file="${source_ref%%:*}"; key="${source_ref#*:}"
    [[ "$variable" =~ ^[A-Z][A-Z0-9_]*$ && "$file" != "$source_ref" ]] || { echo "invalid runtime state mapping: $mapping" >&2; exit 2; }
    value="$(python - "$state_dir/$file" "$key" <<'PY'
import json, pathlib, sys
obj=json.loads(pathlib.Path(sys.argv[1]).read_text()); value=obj.get(sys.argv[2])
if not isinstance(value,str) or not value: raise SystemExit("runtime state value missing")
print(value)
PY
)"
    export "$variable=$value"
  done
  "${compose[@]}" up -d --no-build --wait --wait-timeout "${STACK_READY_TIMEOUT_SECONDS:-180}" \
    "${deferred_services[@]}" 2>&1 | tee "$suite_artifacts/phases/deferred-runtime-start.log"
fi

export E2E_RUNTIME_SERVICES="${runtime_services[*]}"
bash scripts/ci/assert_reference_image_identity.sh 2>&1 | tee "$suite_artifacts/phases/image-identity.log"

if ((${#faults[@]} == 0)); then
  run_runner main 2>&1 | tee "$suite_artifacts/phases/runner.log"
else
  run_runner before-fault 2>&1 | tee "$suite_artifacts/phases/runner-before-fault.log"
  for fault in "${faults[@]}"; do bash scripts/ci/e2e_fault_injection.sh "$fault" 2>&1 | tee -a "$suite_artifacts/phases/faults.log"; done
  run_runner after-fault 2>&1 | tee "$suite_artifacts/phases/runner-after-fault.log"
fi

echo "E2E suite '$requested' passed"
