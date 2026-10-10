#!/usr/bin/env bash
set -euo pipefail

# Ephemeral laboratory PKI. The caller owns the directory lifecycle; neither
# private keys nor this directory belong in sanitized CI artifacts.
output="${1:?usage: create_lab_tls.sh DIRECTORY HOST [HOST ...]}"
shift
(($# > 0)) || { echo 'at least one laboratory hostname is required' >&2; exit 2; }
mkdir -p "$output"
chmod 0700 "$output"
for host in "$@"; do
  [[ "$host" =~ ^[a-z][a-z0-9-]{0,62}$ ]] || {
    echo 'invalid laboratory hostname' >&2
    exit 2
  }
done
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -sha256 \
  -subj '/CN=Request Engine ephemeral laboratory CA' \
  -addext 'basicConstraints=critical,CA:TRUE' \
  -addext 'keyUsage=critical,keyCertSign,cRLSign' \
  -keyout "$output/ca.key" -out "$output/ca.crt" >/dev/null 2>&1
chmod 0600 "$output/ca.key"
for host in "$@"; do
  openssl req -new -newkey rsa:2048 -nodes -sha256 -subj "/CN=$host" \
    -keyout "$output/$host.key" -out "$output/$host.csr" >/dev/null 2>&1
  cat > "$output/$host.ext" <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:$host
EOF
  openssl x509 -req -days 1 -sha256 -in "$output/$host.csr" \
    -CA "$output/ca.crt" -CAkey "$output/ca.key" -CAcreateserial \
    -extfile "$output/$host.ext" -out "$output/$host.crt" >/dev/null 2>&1
  # Bind only this service's leaf key into its container. The parent directory
  # stays private on the host; the CA key is never mounted into a service.
  chmod 0644 "$output/$host.key" "$output/$host.crt" "$output/ca.crt"
  rm "$output/$host.csr" "$output/$host.ext"
  openssl verify -CAfile "$output/ca.crt" -verify_hostname "$host" \
    "$output/$host.crt" >/dev/null
done
