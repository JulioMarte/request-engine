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
  capabilities = ["create", "read", "update"]
}

# Metadata delete is intentionally absent; do not combine this token with a
# policy granting it. Destroy is denied even if another policy grants it.
path "secret/destroy/request-engine/identity-recovery/*" {
  capabilities = ["deny"]
}


# Appointment-option signing keyrings are isolated from ordinary platform and
# recovery secret prefixes. Only the private control plane may mutate them.
path "secret/data/request-engine/signing/*" {
  capabilities = ["create", "update", "read"]
}

path "secret/metadata/request-engine/signing/*" {
  capabilities = ["read", "delete", "update"]
}
