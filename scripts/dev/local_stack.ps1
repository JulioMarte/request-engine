# DEVELOPMENT-ONLY wrapper: .\scripts\dev\local_stack.ps1 up|status|down [--volumes]
# Native progress output (docker/uv) goes to stderr; Windows PowerShell 5.1 turns
# redirected native stderr into terminating errors under 'Stop', so rely on the
# exit code instead.
$ErrorActionPreference = 'Continue'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Push-Location $root
try {
  & uv run python scripts/dev/local_stack.py @args
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
  Pop-Location
}
