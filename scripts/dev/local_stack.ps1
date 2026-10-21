# DEVELOPMENT-ONLY wrapper: .\scripts\dev\local_stack.ps1 up|status|down [--volumes]
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Push-Location $root
try {
  & uv run python scripts/dev/local_stack.py @args
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
  Pop-Location
}
