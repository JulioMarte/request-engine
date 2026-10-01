# Development-only launcher for the admin console + the REAL control plane.
#
# Unlike the old mock, this starts request_engine.bootstrap.platform_server
# against the local PostgreSQL 18 with real least-privilege runtime logins, then
# starts the private admin console pointed at it. Everything the console shows
# and executes is the real control plane and the real database.
#
# It stops stale dev processes and starts both services FULLY DETACHED (via the
# WMI Win32_Process.Create provider, so they never inherit this shell's
# stdout/stderr pipes and cannot block the caller), waits for readiness and
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
  [string]$DbSuperuser = 'request_engine'
)

$ErrorActionPreference = 'Stop'
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

function Start-Detached([string]$CommandLine) {
  # Win32_Process.Create spawns outside this shell; no inherited pipes.
  Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
    CommandLine = $CommandLine
  } | Out-Null
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

$controlCmd = ('cmd.exe /c "cd /d "{0}" && ' +
  'set REQUEST_ENGINE_DATABASE_URL={1}&& ' +
  'set REQUEST_ENGINE_PLATFORM_READ_DATABASE_URL={2}&& ' +
  'set REQUEST_ENGINE_PLATFORM_CONTROL_DATABASE_URL={3}&& ' +
  'set REQUEST_ENGINE_NATIVE_IDENTITY_AUTHORITY_ID={4}&& ' +
  'set REQUEST_ENGINE_WEBAUTHN_DECOY_KEY={5}&& ' +
  'set REQUEST_ENGINE_WEBAUTHN_RP_ID=localhost&& ' +
  'set REQUEST_ENGINE_WEBAUTHN_RP_NAME=Request Engine&& ' +
  'set REQUEST_ENGINE_WEBAUTHN_ALLOWED_ORIGINS=http://localhost:{6}&& ' +
  '"{7}" -m uvicorn request_engine.bootstrap.platform_server:create_app --factory ' +
  '--host 127.0.0.1 --port {8} > "{9}" 2>&1"') -f `
  $Root, $appUrl, $readUrl, $controlDbUrl, $authority, $decoy, $ConsolePort, $python, $ControlPort, $controlLog
Start-Detached $controlCmd

$runtimeCmd = ('cmd.exe /c "cd /d "{0}" && ' +
  'set REQUEST_ENGINE_DATABASE_URL={1}&& ' +
  'set REQUEST_ENGINE_NATIVE_IDENTITY_AUTHORITY_ID={2}&& ' +
  'set REQUEST_ENGINE_APPOINTMENT_OPTION_SIGNING_KEY={3}&& ' +
  'set REQUEST_ENGINE_IDENTITY_EXCHANGE_FINGERPRINT_KEY={4}&& ' +
  'set REQUEST_ENGINE_WEBAUTHN_DECOY_KEY={5}&& ' +
  'set REQUEST_ENGINE_WEBAUTHN_RP_ID=localhost&& ' +
  'set REQUEST_ENGINE_WEBAUTHN_RP_NAME=Request Engine&& ' +
  'set REQUEST_ENGINE_WEBAUTHN_ALLOWED_ORIGINS=http://localhost:{6}&& ' +
  '"{7}" -m uvicorn request_engine.bootstrap.server:create_app --factory ' +
  '--host 127.0.0.1 --port {8} > "{9}" 2>&1"') -f `
  $Root, $appUrl, $authority, $optionSigningSecret, $fingerprintSecret, $decoy, $ConsolePort, $python, $RuntimePort, $runtimeLog
Start-Detached $runtimeCmd

$consoleCmd = ('cmd.exe /c "cd /d "{0}" && set REQUEST_ENGINE_ADMIN_CONSOLE_CONTROL_API_BASE_URL=http://127.0.0.1:{1}&& ' +
  'set REQUEST_ENGINE_ADMIN_CONSOLE_RUNTIME_API_BASE_URL=http://127.0.0.1:{6}&& ' +
  'set REQUEST_ENGINE_ADMIN_CONSOLE_SESSION_SECRET={2}&& ' +
  'set "REQUEST_ENGINE_ADMIN_CONSOLE_SESSION_STORE_DIRECTORY={7}"&& ' +
  'set REQUEST_ENGINE_ADMIN_CONSOLE_COOKIE_SECURE=false&& ' +
  'set REQUEST_ENGINE_ADMIN_CONSOLE_DEBUG=true&& ' +
  '"{3}" -m uvicorn request_engine.bootstrap.admin_console_server:create_app --factory --host 127.0.0.1 --port {4} > "{5}" 2>&1"') -f `
  $Root, $ControlPort, $consoleSessionSecret, $python, $ConsolePort, $consoleLog, $RuntimePort, $sessionDirectory
Start-Detached $consoleCmd

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
Write-Output "ready              : $($controlReady -eq 200 -and $runtimeReady -eq 200 -and $consoleReady -eq 200)"
