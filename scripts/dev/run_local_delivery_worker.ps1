# Start only after setup and legitimate HTTP integration-principal provisioning.
# Supply credential-bearing settings in the caller environment, never arguments.
param([switch]$WithDelivery, [int]$ConsolePort = 8012)
$ErrorActionPreference = 'Stop'
if (-not $WithDelivery) { throw 'Explicit -WithDelivery required (local development only)' }
if (-not (Get-Command Start-Process).Parameters.ContainsKey('Environment')) { throw 'PowerShell 7.4+ required' }
foreach ($required in @('REQUEST_ENGINE_WORKER_PRINCIPAL_ID', 'REQUEST_ENGINE_WORKER_DATABASE_URL', 'REQUEST_ENGINE_APP_DATABASE_URL', 'REQUEST_ENGINE_OUTBOX_PUBLISH_URL')) {
  if (-not [Environment]::GetEnvironmentVariable($required)) { throw "Missing prerequisite $required; do not manufacture business authority" }
}
$principal = [guid]::Empty
if (-not [guid]::TryParse($env:REQUEST_ENGINE_WORKER_PRINCIPAL_ID, [ref]$principal) -or $principal -eq [guid]::Empty) { throw 'A genuine integration principal UUID is required' }
$publisher = [uri]$env:REQUEST_ENGINE_OUTBOX_PUBLISH_URL
if ($publisher.Scheme -notin @('http', 'https') -or $publisher.Host -notin @('localhost', '127.0.0.1', '::1') -or $publisher.UserInfo) {
  throw 'Development outbox receiver must be explicitly configured on loopback without URL credentials'
}
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$python = Join-Path $repositoryRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run uv sync first' }
. (Join-Path $PSScriptRoot 'local_panel_delivery.ps1')
$delivery = Start-PanelLocalDelivery $repositoryRoot 58241 58242 58243
$environment = @{
  REQUEST_ENGINE_WORKER_FACTORY = 'request_engine.bootstrap.reference_worker_factory:create_worker'
  REQUEST_ENGINE_WORKER_PRINCIPAL_ID = $env:REQUEST_ENGINE_WORKER_PRINCIPAL_ID
  REQUEST_ENGINE_WORKER_DATABASE_URL = $env:REQUEST_ENGINE_WORKER_DATABASE_URL
  REQUEST_ENGINE_APP_DATABASE_URL = $env:REQUEST_ENGINE_APP_DATABASE_URL
  REQUEST_ENGINE_OUTBOX_PUBLISHER_FACTORY = 'request_engine.bootstrap.http_outbox_publisher:create_publisher'
  REQUEST_ENGINE_OUTBOX_PUBLISH_URL = $env:REQUEST_ENGINE_OUTBOX_PUBLISH_URL
  REQUEST_ENGINE_OPENBAO_ADDR = $delivery.Address
  REQUEST_ENGINE_OPENBAO_TOKEN = $delivery.RuntimeToken
  REQUEST_ENGINE_OPENBAO_MOUNT = 'secret'
  REQUEST_ENGINE_OPENBAO_NAMESPACE = ''
  REQUEST_ENGINE_OPENBAO_PATH_PREFIX = 'request-engine/identity-recovery'
  REQUEST_ENGINE_VAULT_ADDR = ''
  REQUEST_ENGINE_VAULT_TOKEN = ''
  REQUEST_ENGINE_SMTP_HOST = '127.0.0.1'
  REQUEST_ENGINE_SMTP_PORT = '58242'
  REQUEST_ENGINE_SMTP_SENDER = 'request-engine@localhost.test'
  REQUEST_ENGINE_SMTP_USERNAME = ''
  REQUEST_ENGINE_SMTP_PASSWORD = ''
  REQUEST_ENGINE_SMTP_STARTTLS = 'false'
  REQUEST_ENGINE_SMTP_SSL = 'false'
  REQUEST_ENGINE_STAFF_INVITATION_ACCEPT_URL = "http://localhost:$ConsolePort/staff-invitations"
}
$logDirectory = Join-Path $env:TEMP 're-admin'
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$outputLog = Join-Path $logDirectory 'delivery-worker.log'
Start-Process -FilePath $python -WorkingDirectory $repositoryRoot -WindowStyle Hidden `
  -ArgumentList @('-c', '"from request_engine.entrypoints.worker.cli import main; main()"') `
  -Environment $environment -RedirectStandardOutput $outputLog -RedirectStandardError "$outputLog.err" | Out-Null
Write-Output 'Worker process launched; not a delivery/readiness certification. Inspect sanitized operational status and Mailpit for the actual invitation.'
