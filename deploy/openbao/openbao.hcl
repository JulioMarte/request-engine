ui = true
disable_mlock = true

storage "raft" {
  path    = "/openbao/data"
  node_id = "request-engine-openbao-1"
}

listener "tcp" {
  address         = "0.0.0.0:8200"
  cluster_address = "0.0.0.0:8201"
  tls_cert_file   = "/openbao/tls/tls.crt"
  tls_key_file    = "/openbao/tls/tls.key"
}

api_addr     = "https://openbao:8200"
cluster_addr = "https://openbao:8201"
