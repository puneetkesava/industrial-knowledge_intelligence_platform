# Fast-path: enqueue high-value pending docs (no drawings).
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $repoRoot

$idsFile = Join-Path $repoRoot 'high_value_ids.txt'
if (-not (Test-Path $idsFile)) {
  throw "Missing $idsFile - export IDs first"
}

$base = 'http://localhost:8000'
$login = Invoke-RestMethod -Method Post -Uri "$base/api/v1/auth/login" -ContentType 'application/json' -Body '{"email":"admin@example.com","password":"ChangeMeAdmin!"}'
$headers = @{
  Authorization  = "Bearer $($login.data.access_token)"
  'Content-Type' = 'application/json'
}

$ids = @(Get-Content $idsFile | Where-Object { $_.Trim() } | ForEach-Object { $_.Trim() })
Write-Host "Enqueueing $($ids.Count) high-value docs..."

$batchSize = 250
$queued = 0
for ($i = 0; $i -lt $ids.Count; $i += $batchSize) {
  $end = [Math]::Min($i + $batchSize - 1, $ids.Count - 1)
  $batch = @($ids[$i..$end])
  $body = (@{
      document_ids = $batch
      async_worker = $true
      hero_only    = $false
      limit        = $batch.Count
    } | ConvertTo-Json -Compress -Depth 5)
  $enq = Invoke-RestMethod -Method Post -Uri "$base/api/v1/indexing/priority-enqueue" -Headers $headers -Body $body -TimeoutSec 180
  $queued += $enq.data.queued.Count
  Write-Host ("  queued {0}/{1}" -f $queued, $ids.Count)
}

Write-Host "TOTAL_QUEUED=$queued"
$idx = Invoke-RestMethod -Uri "$base/api/v1/indexing/status" -Headers $headers
Write-Host ($idx.data | ConvertTo-Json -Compress)
