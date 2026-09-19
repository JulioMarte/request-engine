# Control-plane secret lifecycle. No access outside Request Engine prefixes.
path "secret/data/request-engine/platform/*" {
  capabilities = ["create", "update", "read"]
}

path "secret/metadata/request-engine/platform/*" {
  capabilities = ["read", "delete", "update"]
}

path "secret/data/request-engine/identity-recovery/*" {
  capabilities = ["create", "update", "read"]
}

path "secret/metadata/request-engine/identity-recovery/*" {
  capabilities = ["read", "delete", "update"]
}
