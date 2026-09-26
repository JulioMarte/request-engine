# Runtime read access only. Control-plane secret mutation uses a separate role.
path "secret/data/request-engine/platform/*" {
  capabilities = ["read"]
}

path "secret/metadata/request-engine/platform/*" {
  capabilities = ["read"]
}

path "secret/data/request-engine/identity-recovery/*" {
  capabilities = ["read"]
}

path "secret/metadata/request-engine/identity-recovery/*" {
  capabilities = ["read"]
}
