# Public HTTP signing runtime: read-only and signing-family scoped.
path "secret/data/request-engine/signing/*" {
  capabilities = ["read"]
}

path "secret/metadata/request-engine/signing/*" {
  capabilities = ["read"]
}
