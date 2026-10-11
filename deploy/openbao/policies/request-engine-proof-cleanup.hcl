# Dedicated expiry janitor: no plaintext reads, writes, listing or metadata delete.
# Configure on a separate AppRole; never combine with broader policies.
path "secret/metadata/request-engine/identity-recovery/*" {
  capabilities = ["read"]
}
path "secret/destroy/request-engine/identity-recovery/*" {
  capabilities = ["update"]
}
path "secret/data/request-engine/identity-recovery/*" {
  capabilities = ["deny"]
}
