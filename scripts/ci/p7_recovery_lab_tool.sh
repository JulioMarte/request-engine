#!/usr/bin/env bash
set -euo pipefail

tool="$(basename "$0")"
case "$tool" in
  age)
    : "${P7_AGE_IMAGE:?P7_AGE_IMAGE is required}"
    : "${P7_AGE_WORKSPACE:?P7_AGE_WORKSPACE is required}"
    rewritten=()
    for argument in "$@"; do
      case "$argument" in
        "$P7_AGE_WORKSPACE"/*)
          rewritten+=("/workspace/${argument#"$P7_AGE_WORKSPACE"/}")
          ;;
        *) rewritten+=("$argument") ;;
      esac
    done
    exec docker run --rm --user "$(id -u):$(id -g)" \
      --mount "type=bind,src=$P7_AGE_WORKSPACE,dst=/workspace" \
      "$P7_AGE_IMAGE" age "${rewritten[@]}"
    ;;
  pg_dump)
    : "${P7_PG_SOURCE_CONTAINER:?P7_PG_SOURCE_CONTAINER is required}"
    : "${P7_PG_DATABASE:?P7_PG_DATABASE is required}"
    output=""
    options=()
    while (($#)); do
      case "$1" in
        --file)
          shift
          output="${1:?pg_dump --file value is missing}"
          ;;
        --file=*) output="${1#--file=}" ;;
        *) options+=("$1") ;;
      esac
      shift
    done
    [[ -n "$output" ]] || { echo 'pg_dump wrapper requires --file' >&2; exit 2; }
    docker exec "$P7_PG_SOURCE_CONTAINER" pg_dump \
      --username=postgres --dbname="$P7_PG_DATABASE" "${options[@]}" --file=- >"$output"
    ;;
  pg_restore)
    : "${P7_PG_TARGET_CONTAINER:?P7_PG_TARGET_CONTAINER is required}"
    database=""
    dump=""
    options=()
    while (($#)); do
      case "$1" in
        --dbname)
          shift
          database="${1:?pg_restore --dbname value is missing}"
          ;;
        --dbname=*) database="${1#--dbname=}" ;;
        /*) dump="$1" ;;
        *) options+=("$1") ;;
      esac
      shift
    done
    [[ -n "$database" && -n "$dump" ]] || {
      echo 'pg_restore wrapper requires --dbname and an archive path' >&2
      exit 2
    }
    remote_dump="/tmp/p7-offhost-restore-$$.dump"
    docker cp "$dump" "$P7_PG_TARGET_CONTAINER:$remote_dump" >/dev/null
    docker exec "$P7_PG_TARGET_CONTAINER" pg_restore \
      --username=postgres "${options[@]}" --dbname="$database" "$remote_dump"
    docker exec "$P7_PG_TARGET_CONTAINER" rm -f "$remote_dump"
    ;;
  bao)
    (($# >= 5)) || { echo 'bao wrapper received an incomplete command' >&2; exit 2; }
    if [[ "$1 $2 $3 $4" == "operator raft snapshot save" ]]; then
      : "${P7_OPENBAO_SOURCE_CONTAINER:?P7_OPENBAO_SOURCE_CONTAINER is required}"
      : "${P7_OPENBAO_SOURCE_TOKEN:?P7_OPENBAO_SOURCE_TOKEN is required}"
      destination="${5:?snapshot destination is missing}"
      remote="/tmp/p7-offhost-source-$$.snap"
      BAO_TOKEN="$P7_OPENBAO_SOURCE_TOKEN" docker exec \
        -e BAO_ADDR=http://127.0.0.1:8200 -e BAO_TOKEN \
        "$P7_OPENBAO_SOURCE_CONTAINER" bao operator raft snapshot save "$remote"
      docker cp "$P7_OPENBAO_SOURCE_CONTAINER:$remote" "$destination" >/dev/null
      docker exec "$P7_OPENBAO_SOURCE_CONTAINER" rm -f "$remote"
    elif [[ "$1 $2 $3 $4" == "operator raft snapshot restore" && "$5" == "-force" ]]; then
      : "${P7_OPENBAO_TARGET_CONTAINER:?P7_OPENBAO_TARGET_CONTAINER is required}"
      : "${P7_OPENBAO_TARGET_TOKEN:?P7_OPENBAO_TARGET_TOKEN is required}"
      snapshot="${6:?snapshot path is missing}"
      remote="/tmp/p7-offhost-target-$$.snap"
      docker cp "$snapshot" "$P7_OPENBAO_TARGET_CONTAINER:$remote" >/dev/null
      BAO_TOKEN="$P7_OPENBAO_TARGET_TOKEN" docker exec \
        -e BAO_ADDR=http://127.0.0.1:8200 -e BAO_TOKEN \
        "$P7_OPENBAO_TARGET_CONTAINER" bao operator raft snapshot restore -force "$remote"
      docker exec "$P7_OPENBAO_TARGET_CONTAINER" rm -f "$remote"
    else
      echo 'unsupported OpenBao wrapper command' >&2
      exit 2
    fi
    ;;
  *) echo "unsupported recovery lab command: $tool" >&2; exit 2 ;;
esac
