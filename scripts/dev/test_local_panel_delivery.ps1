# Opt-in real provider proof. Does not connect to PostgreSQL or start the panel.
param([switch]$RunRealProviders)
$ErrorActionPreference = 'Stop'
if (-not $RunRealProviders) { throw 'Explicit -RunRealProviders required (development containers only)' }
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
. (Join-Path $PSScriptRoot 'local_panel_delivery.ps1')
$delivery = Start-PanelLocalDelivery $repositoryRoot 58241 58242 58243
$headers = @{ 'X-Vault-Token' = $delivery.RuntimeToken }
$proofPath = 'request-engine/identity-recovery/launcher-probe-' + [guid]::NewGuid().ToString('N')
try {
  Invoke-RestMethod "$($delivery.Address)/v1/secret/metadata/$proofPath" -Method Post -Headers $headers `
    -ContentType application/json -Body '{"delete_version_after":"60s"}' | Out-Null
  Invoke-RestMethod "$($delivery.Address)/v1/secret/data/$proofPath" -Method Post -Headers $headers `
    -ContentType application/json -Body '{"options":{"cas":0},"data":{"probe":"non-secret-provider-proof"}}' | Out-Null
  $metadata = Invoke-RestMethod "$($delivery.Address)/v1/secret/metadata/$proofPath" -Headers $headers
  if (-not $metadata.data.versions.'1'.deletion_time) { throw 'First version has no expiry' }
  $read = Invoke-RestMethod "$($delivery.Address)/v1/secret/data/$proofPath" -Headers $headers
  if ($read.data.data.probe -ne 'non-secret-provider-proof') { throw 'Read oracle mismatch' }
  foreach ($negative in @(
    @{ Uri = "secret/metadata/$proofPath"; Method = 'Delete'; Body = $null },
    @{ Uri = "secret/destroy/$proofPath"; Method = 'Post'; Body = '{"versions":[1]}' },
    @{ Uri = 'secret/data/request-engine/platform/launcher-negative'; Method = 'Post'; Body = '{"data":{"probe":"no-write"}}' }
  )) {
    $status = 0
    try {
      Invoke-RestMethod "$($delivery.Address)/v1/$($negative.Uri)" -Headers $headers `
        -Method $negative.Method -ContentType application/json -Body $negative.Body | Out-Null
    } catch { $status = [int]$_.Exception.Response.StatusCode }
    if ($status -ne 403) { throw 'Least-privilege negative oracle failed' }
  }
  $subject = 'Local launcher provider proof ' + [guid]::NewGuid().ToString('N')
  $client = [System.Net.Mail.SmtpClient]::new('127.0.0.1', 58242)
  try { $client.Send('request-engine@localhost.test', 'launcher-probe@localhost.test', $subject, 'Non-secret SMTP transport proof.') }
  finally { $client.Dispose() }
  $messages = Invoke-RestMethod 'http://127.0.0.1:58243/api/v1/messages'
  if (@($messages.messages | Where-Object { $_.Subject -eq $subject }).Count -ne 1) {
    throw 'Mailpit inbox oracle missing'
  }
} catch { throw 'Local provider proof failed; credentials and provider response details suppressed' }
Write-Output 'PASS: real OpenBao KV v2 first-version TTL/read; metadata-delete/destroy/managed-write denied; real SMTP captured in Mailpit.'
Write-Output 'No PostgreSQL access; no invitation worker or recipient journey certified. Probe version expires after 60 seconds (soft deletion only).'
