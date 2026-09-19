vault {
  address = "https://openbao:8200"
  ca_cert = "/openbao/tls/ca.crt"
}

auto_auth {
  method "approle" {
    config = {
      role_id_file_path                  = "/run/openbao-auth/role-id"
      secret_id_file_path                = "/run/openbao-auth/secret-id"
      remove_secret_id_file_after_reading = true
      secret_id_response_wrapping_path   = "auth/approle/role/request-engine-runtime/secret-id"
    }
  }
}

api_proxy {
  use_auto_auth_token = "force"
}

listener "tcp" {
  address     = "0.0.0.0:8100"
  tls_disable = true
}
