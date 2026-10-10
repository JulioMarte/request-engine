# Development-only launcher for the admin console + the REAL control plane.
#
# Unlike the old mock, this starts request_engine.bootstrap.platform_server
# against the local PostgreSQL 18 with real least-privilege runtime logins, then
# starts the private admin console pointed at it. Everything the console shows
# and executes is the real control plane and the real database.
#
# It stops stale dev processes and starts services detached with explicit
# environment maps (secrets never appear in command arguments), waits for readiness and
# prints the URLs. It returns promptly and never runs a server in the foreground.
#
# Prereqs: `uv sync`, the local PostgreSQL container up, and the database
# migrated to head (`alembic upgrade head`). NOT for production.
#
# The first visit should complete the setup wizard (the instance starts
# `unclaimed`); use http://localhost:<ConsolePort> (not 127.0.0.1) so the browser
# treats it as a secure context for passkeys.
param(
  [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
  [int]$ControlPort = 8001,
  [int]$ConsolePort = 8002,
  [int]$RuntimePort = 8000,
  [string]$Container = 'request-engine-postgres-1',
  [string]$Database = 'request_engine_current',
  [string]$DbSuperuser = 'request_engine',
  [switch]$WithDelivery,
  [int]$OpenBaoPort = 58241,
  [int]$SmtpPort = 58242,
  [int]$MailpitPort = 58243
)

$ErrorActionPreference = 'Stop'
if (-not (Get-Command Start-Process).Parameters.ContainsKey('Environment')) {
  throw 'PowerShell 7.4+ required: application secrets must not be embedded in process arguments'
}
. (Join-Path $PSScriptRoot 'local_panel_delivery.ps1')
$log = Join-Path $env:TEMP 're-admin'
New-Item -ItemType Directory -Force -Path $log | Out-Null

$python = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
  throw "venv python not found at $python; run 'uv sync' first"
}

# Fail before role provisioning when the selected database is behind the repo.
$headOutput = @(& $python -m alembic -c (Join-Path $Root 'alembic.ini') heads)
if ($LASTEXITCODE -ne 0) { throw 'cannot resolve repository Alembic head' }
if ($headOutput.Count -ne 1) { throw 'expected exactly one repository Alembic head' }
$expectedHead = $headOutput[0].Split(' ')[0].Trim()
$actualHeadOutput = docker exec $Container psql -U $DbSuperuser -d $Database -t -A `
  -c "SELECT version_num FROM alembic_version"
if ($LASTEXITCODE -ne 0) {
  throw "cannot read alembic_version from $Database; initialize and migrate the database first"
}
$actualHead = ($actualHeadOutput | Out-String).Trim()
if (-not $expectedHead -or $actualHead -ne $expectedHead) {
  throw "database migration mismatch: repository=$expectedHead database=$actualHead; run alembic upgrade head first"
}

# A failed preflight must not take down the user's already-running panel.
$escapedRoot = [regex]::Escape($Root)
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='cmd.exe'" |
  Where-Object {
    $_.CommandLine -match $escapedRoot -and
    $_.CommandLine -match 'uvicorn|mock_control_plane|platform_server|admin_console_server'
  } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2

# Idempotently create the three least-privilege runtime logins the control
# plane verifies at startup. Dev-only throwaway passwords.
$rolesSql = Join-Path $Root 'scripts\dev\init_local_runtime_roles.sql'
Get-Content -Raw -LiteralPath $rolesSql |
  docker exec -i $Container psql -U $DbSuperuser -d $Database -v ON_ERROR_STOP=1 | Out-Null
if ($LASTEXITCODE -ne 0) { throw "failed to provision local runtime roles" }

$authority = (
  docker exec $Container psql -U $DbSuperuser -d $Database -t -A `
    -c "SELECT built_in_native_authority_id FROM request_engine.platform_instance"
).Trim()
if (-not $authority) {
  throw "no platform_instance found in $Database; run 'alembic upgrade head' first"
}

function Start-PanelServer([string]$Module, [int]$Port, [hashtable]$Environment, [string]$OutputLog) {
  Start-Process -FilePath $python -WorkingDirectory $Root -WindowStyle Hidden `
    -ArgumentList @('-m', 'uvicorn', "${Module}:create_app", '--factory', '--host', '127.0.0.1', '--port', "$Port") `
    -Environment $Environment -RedirectStandardOutput $OutputLog -RedirectStandardError "$OutputLog.err" | Out-Null
}

function New-DevelopmentSecret {
  $bytes = New-Object byte[] 48
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
  return [Convert]::ToBase64String($bytes)
}
$optionSigningSecret = New-DevelopmentSecret
$fingerprintSecret = New-DevelopmentSecret
$consoleSessionSecret = New-DevelopmentSecret
$decoy = New-DevelopmentSecret
$sessionDirectory = Join-Path $Root '.local-ci/admin-console-sessions'
New-Item -ItemType Directory -Force -Path $sessionDirectory | Out-Null
$controlLog = Join-Path $log 'control-plane.log'
$runtimeLog = Join-Path $log 'runtime.log'
$consoleLog = Join-Path $log 'console.log'

$appUrl = "postgresql+asyncpg://re_dev_app:dev-app-only@127.0.0.1:5432/$Database"
$readUrl = "postgresql+asyncpg://re_dev_read:dev-read-only@127.0.0.1:5432/$Database"
$controlDbUrl = "postgresql+asyncpg://re_dev_control:dev-control-only@127.0.0.1:5432/$Database"

$shared = @{
  REQUEST_ENGINE_DATABASE_URL = $appUrl
  REQUEST_ENGINE_NATIVE_IDENTITY_AUTHORITY_ID = $authority
  REQUEST_ENGINE_WEBAUTHN_DECOY_KEY = $decoy
  REQUEST_ENGINE_WEBAUTHN_RP_ID = 'localhost'
  REQUEST_ENGINE_WEBAUTHN_RP_NAME = 'Request Engine'
  REQUEST_ENGINE_WEBAUTHN_ALLOWED_ORIGINS = "http://localhost:$ConsolePort"
}
if ($WithDelivery) {
  $delivery = Start-PanelLocalDelivery $Root $OpenBaoPort $SmtpPort $MailpitPort
  $shared.REQUEST_ENGINE_OPENBAO_ADDR = $delivery.Address
  $shared.REQUEST_ENGINE_OPENBAO_MOUNT = 'secret'
  $shared.REQUEST_ENGINE_OPENBAO_NAMESPACE = ''
  $shared.REQUEST_ENGINE_OPENBAO_PATH_PREFIX = 'request-engine/identity-recovery'
  $shared.REQUEST_ENGINE_VAULT_ADDR = ''
  $shared.REQUEST_ENGINE_VAULT_TOKEN = ''
  $shared.REQUEST_ENGINE_SMTP_HOST = '127.0.0.1'
  $shared.REQUEST_ENGINE_SMTP_PORT = "$SmtpPort"
  $shared.REQUEST_ENGINE_SMTP_SENDER = 'request-engine@localhost.test'
  $shared.REQUEST_ENGINE_SMTP_STARTTLS = 'false'
  $shared.REQUEST_ENGINE_SMTP_SSL = 'false'
  $shared.REQUEST_ENGINE_SMTP_USERNAME = ''
  $shared.REQUEST_ENGINE_SMTP_PASSWORD = ''
  $shared.REQUEST_ENGINE_STAFF_INVITATION_ACCEPT_URL = "http://localhost:$ConsolePort/staff-invitations"
}
$controlEnvironment = $shared.Clone()
$controlEnvironment.REQUEST_ENGINE_PLATFORM_READ_DATABASE_URL = $readUrl
$controlEnvironment.REQUEST_ENGINE_PLATFORM_CONTROL_DATABASE_URL = $controlDbUrl
if ($WithDelivery) { $controlEnvironment.REQUEST_ENGINE_OPENBAO_TOKEN = $delivery.ControlToken }
$runtimeEnvironment = $shared.Clone()
$runtimeEnvironment.REQUEST_ENGINE_APPOINTMENT_OPTION_SIGNING_KEY = $optionSigningSecret
$runtimeEnvironment.REQUEST_ENGINE_IDENTITY_EXCHANGE_FINGERPRINT_KEY = $fingerprintSecret
if ($WithDelivery) { $runtimeEnvironment.REQUEST_ENGINE_OPENBAO_TOKEN = $delivery.RuntimeToken }
$consoleEnvironment = @{
  REQUEST_ENGINE_ADMIN_CONSOLE_CONTROL_API_BASE_URL = "http://127.0.0.1:$ControlPort"
  REQUEST_ENGINE_ADMIN_CONSOLE_RUNTIME_API_BASE_URL = "http://127.0.0.1:$RuntimePort"
  REQUEST_ENGINE_ADMIN_CONSOLE_SESSION_SECRET = $consoleSessionSecret
  REQUEST_ENGINE_ADMIN_CONSOLE_SESSION_STORE_DIRECTORY = $sessionDirectory
  REQUEST_ENGINE_ADMIN_CONSOLE_COOKIE_SECURE = 'false'
  REQUEST_ENGINE_ADMIN_CONSOLE_DEBUG = 'true'
}
Start-PanelServer 'request_engine.bootstrap.platform_server' $ControlPort $controlEnvironment $controlLog
Start-PanelServer 'request_engine.bootstrap.server' $RuntimePort $runtimeEnvironment $runtimeLog
Start-PanelServer 'request_engine.bootstrap.admin_console_server' $ConsolePort $consoleEnvironment $consoleLog

function Wait-Http([string]$Url, [int]$Seconds) {
  $deadline = (Get-Date).AddSeconds($Seconds)
  do {
    Start-Sleep -Seconds 2
    try { return (Invoke-WebRequest -UseBasicParsing $Url -TimeoutSec 3).StatusCode } catch { }
  } until ((Get-Date) -gt $deadline)
  return $null
}

$controlReady = Wait-Http "http://127.0.0.1:$ControlPort/health/ready" 60
$runtimeReady = Wait-Http "http://127.0.0.1:$RuntimePort/health/ready" 60
$consoleReady = Wait-Http "http://127.0.0.1:$ConsolePort/health/live" 60
if ($runtimeReady -ne 200) { throw "runtime did not become ready; see $runtimeLog" }
if ($controlReady -ne 200) { throw "control plane did not become ready; see $controlLog" }
if ($consoleReady -ne 200) { throw "admin console did not become ready; see $consoleLog" }

Write-Output "real control plane : http://127.0.0.1:$ControlPort  (health/ready = $controlReady)"
Write-Output "tenant runtime     : http://127.0.0.1:$RuntimePort  (health/ready = $runtimeReady)"
Write-Output "admin console      : http://localhost:$ConsolePort  (use localhost, not 127.0.0.1, for passkeys)"
Write-Output "database           : $Database  (instance authority $authority)"
Write-Output "logs               : $log"
if ($WithDelivery) {
  Write-Output "local mail inbox   : http://127.0.0.1:$MailpitPort (development only; contains sensitive links)"
  Write-Output 'delivery worker    : NOT started; provision an integration principal through APIs and follow docs/testing/local-panel-delivery.md'
}
Write-Output "ready              : $($controlReady -eq 200 -and $runtimeReady -eq 200 -and $consoleReady -eq 200)"
