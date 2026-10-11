# Native recovery / staff invitation proof issuance; no managed-secret mutation.
path "secret/data/request-engine/identity-recovery/*" {
  capabilities = ["create", "update", "read"]
}
path "secret/metadata/request-engine/identity-recovery/*" {
  capabilities = ["create", "read", "update"]
}
path "secret/destroy/request-engine/identity-recovery/*" {
  capabilities = ["deny"]
}
