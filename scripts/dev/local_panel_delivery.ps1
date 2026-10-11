# Development-only infrastructure. Dot-sourcing defines functions, starts nothing.
function New-PanelDevelopmentSecret {
  $bytes = [byte[]]::new(48)
  [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
  return [Convert]::ToBase64String($bytes)
}

function Start-PanelLocalDelivery([string]$RepositoryRoot, [int]$BaoPort, [int]$MailPort, [int]$MailUiPort) {
  $owner = 'request-engine-panel-dev'
  $baoName = "$owner-openbao"
  $mailName = "$owner-mailpit"
  foreach ($port in @($BaoPort, $MailPort, $MailUiPort)) {
    if ($port -lt 1024 -or $port -gt 65535 -or $port -in @(5432, 58239, 58240)) {
      throw 'Development delivery ports must be unprivileged, distinct from PostgreSQL and agent ports'
    }
  }
  if (@($BaoPort, $MailPort, $MailUiPort | Select-Object -Unique).Count -ne 3) {
    throw 'Development delivery ports must be distinct'
  }
  foreach ($name in @($baoName, $mailName)) {
    $existing = @(& docker ps -a --filter "name=^/$name`$" --format '{{.Names}}')
    if ($LASTEXITCODE -ne 0) { throw 'Docker is required for local delivery' }
    if ($existing.Count -gt 0) {
      $label = & docker inspect --format '{{index .Config.Labels "request-engine.dev-owner"}}' $name
      if ($label -ne $owner) { throw 'Refusing to use an unowned delivery container' }
    }
  }
  $baoExists = @(& docker ps -a --filter "name=^/$baoName`$" --format '{{.Names}}').Count -gt 0
  if (-not $baoExists) {
    $previousToken = $env:BAO_DEV_ROOT_TOKEN_ID
    try {
      $env:BAO_DEV_ROOT_TOKEN_ID = New-PanelDevelopmentSecret
      # Docker receives the value from the environment, never a command argument.
      # Dev server logs include its root token: disable container log persistence.
      & docker run -d --name $baoName --label "request-engine.dev-owner=$owner" `
        --log-driver none --cap-add IPC_LOCK -p "127.0.0.1:${BaoPort}:8200" `
        --env BAO_DEV_ROOT_TOKEN_ID openbao/openbao:2.6.1 server -dev '-dev-listen-address=0.0.0.0:8200' | Out-Null
      if ($LASTEXITCODE -ne 0) { throw 'Cannot start development OpenBao' }
    } finally { $env:BAO_DEV_ROOT_TOKEN_ID = $previousToken }
  }
  # Reuse preserves proof references. Root exists only in this dev container's
  # environment and local process memory; never print this inspect result.
  $configuration = (& docker inspect $baoName | ConvertFrom-Json)[0]
  $mappedPort = $configuration.HostConfig.PortBindings.'8200/tcp'[0]
  if ($mappedPort.HostIp -ne '127.0.0.1' -or $mappedPort.HostPort -ne "$BaoPort") {
    throw 'Existing development OpenBao port differs; explicitly remove it before changing ports'
  }
  $rootEntry = @($configuration.Config.Env | Where-Object { $_.StartsWith('BAO_DEV_ROOT_TOKEN_ID=') })
  if ($rootEntry.Count -ne 1) { throw 'Owned development OpenBao has no bootstrap credential' }
  $rootToken = $rootEntry[0].Substring('BAO_DEV_ROOT_TOKEN_ID='.Length)
  & docker start $baoName | Out-Null
  $address = "http://127.0.0.1:$BaoPort"
  $headers = @{ 'X-Vault-Token' = $rootToken }
  $ready = $false
  for ($attempt = 0; $attempt -lt 30; $attempt++) {
    try {
      Invoke-RestMethod "$address/v1/sys/health" -TimeoutSec 2 | Out-Null
      $ready = $true; break
    } catch { Start-Sleep -Milliseconds 300 }
  }
  if (-not $ready) { throw 'Development OpenBao did not become ready' }
  try {
    $mounts = Invoke-RestMethod "$address/v1/sys/mounts" -Headers $headers
    if (-not $mounts.data.'secret/') {
      Invoke-RestMethod "$address/v1/sys/mounts/secret" -Method Post -Headers $headers `
        -ContentType application/json -Body '{"type":"kv","options":{"version":"2"}}' | Out-Null
    } elseif ($mounts.data.'secret/'.options.version -ne '2') { throw 'KV v2 required' }
    foreach ($policy in @('control', 'runtime', 'proof-writer')) {
      $content = Get-Content -Raw -LiteralPath (Join-Path $RepositoryRoot "deploy/openbao/policies/request-engine-$policy.hcl")
      Invoke-RestMethod "$address/v1/sys/policies/acl/panel-dev-$policy" -Method Put -Headers $headers `
        -ContentType application/json -Body (@{ policy = $content } | ConvertTo-Json) | Out-Null
    }
    $tokens = @{}
    foreach ($role in @('control', 'runtime')) {
      $policies = if ($role -eq 'control') { @('panel-dev-control') } else { @('panel-dev-runtime', 'panel-dev-proof-writer') }
      $response = Invoke-RestMethod "$address/v1/auth/token/create" -Method Post -Headers $headers `
        -ContentType application/json -Body (@{ policies = $policies; no_default_policy = $true; ttl = '8h'; renewable = $false } | ConvertTo-Json)
      $tokens[$role] = $response.auth.client_token
    }
  } catch { throw 'Development OpenBao KV/policy/token bootstrap failed (details suppressed to protect credentials)' }
  $mailExists = @(& docker ps -a --filter "name=^/$mailName`$" --format '{{.Names}}').Count -gt 0
  if (-not $mailExists) {
    & docker run -d --name $mailName --label "request-engine.dev-owner=$owner" --log-driver none `
      -p "127.0.0.1:${MailPort}:1025" -p "127.0.0.1:${MailUiPort}:8025" axllent/mailpit:v1.27 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Cannot start development Mailpit' }
  }
  $mailConfiguration = (& docker inspect $mailName | ConvertFrom-Json)[0]
  foreach ($mapping in @(@('1025/tcp', $MailPort), @('8025/tcp', $MailUiPort))) {
    $binding = $mailConfiguration.HostConfig.PortBindings.($mapping[0])[0]
    if ($binding.HostIp -ne '127.0.0.1' -or $binding.HostPort -ne "$($mapping[1])") {
      throw 'Existing development Mailpit ports differ; explicitly remove it before changing ports'
    }
  }
  & docker start $mailName | Out-Null
  # Caller must not serialize or display this secret-bearing return value.
  return @{ Address = $address; ControlToken = $tokens.control; RuntimeToken = $tokens.runtime }
}
