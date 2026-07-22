# Fast-path orchestration for midnight demo readiness.
# Run from repo root:
#   powershell -NoProfile -ExecutionPolicy Bypass -File backend\scripts\fast_path_midnight.ps1
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $repoRoot

function Get-AuthHeaders {
  $login = Invoke-RestMethod -Method Post -Uri 'http://localhost:8000/api/v1/auth/login' `
    -ContentType 'application/json' `
    -Body '{"email":"admin@example.com","password":"ChangeMeAdmin!"}'
  return @{
    Authorization  = "Bearer $($login.data.access_token)"
    'Content-Type' = 'application/json'
  }
}

Write-Host '=== 1) Ensure Redis queues empty / worker concurrency 6 ==='
docker stop industrial-brain-worker-1 | Out-Null
docker exec industrial-brain-redis-1 redis-cli -n 0 FLUSHDB | Out-Null
docker exec industrial-brain-redis-1 redis-cli -n 1 FLUSHDB | Out-Null
docker compose up -d --no-deps --force-recreate worker | Out-Host
Start-Sleep -Seconds 12
docker cp backend/app/indexing/pipeline.py industrial-brain-worker-1:/app/app/indexing/pipeline.py
docker cp backend/app/extraction/service.py industrial-brain-worker-1:/app/app/extraction/service.py
docker cp backend/app/db/models/extraction.py industrial-brain-worker-1:/app/app/db/models/extraction.py
docker restart industrial-brain-worker-1 | Out-Null
Start-Sleep -Seconds 18
$cmd = docker inspect industrial-brain-worker-1 --format '{{json .Config.Cmd}}'
Write-Host "worker cmd: $cmd"

Write-Host '=== 2) Export high-value pending IDs ==='
$idsFile = Join-Path $repoRoot 'high_value_ids.txt'
docker exec industrial-brain-postgres-1 psql -U industrial_brain -d industrial_brain -t -A -c @"
WITH base AS (
  SELECT d.id
  FROM documents d
  JOIN document_catalog c ON c.id = d.catalog_id
  WHERE d.status = 'uploaded'
    AND c.doc_category IN (
      'test_report','manual','maintenance','sop','safety',
      'regulation','sensor','work_order'
    )
),
datasheets AS (
  SELECT id FROM (
    SELECT d.id,
           row_number() OVER (
             PARTITION BY COALESCE(c.metadata->>'asset_domain','')
             ORDER BY d.created_at
           ) AS rn
    FROM documents d
    JOIN document_catalog c ON c.id = d.catalog_id
    WHERE d.status = 'uploaded' AND c.doc_category = 'datasheet'
  ) x WHERE rn <= 200
)
SELECT id FROM base
UNION ALL
SELECT id FROM datasheets;
"@ | Where-Object { $_.Trim() } | Set-Content -Encoding ascii $idsFile

$ids = @(Get-Content $idsFile | Where-Object { $_.Trim() } | ForEach-Object { $_.Trim() })
Write-Host "High-value IDs: $($ids.Count)"

Write-Host '=== 3) Enqueue batches ==='
$headers = Get-AuthHeaders
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
  $enq = Invoke-RestMethod -Method Post -Uri 'http://localhost:8000/api/v1/indexing/priority-enqueue' `
    -Headers $headers -Body $body -TimeoutSec 180
  $queued += $enq.data.queued.Count
  Write-Host ("  queued {0}/{1}" -f $queued, $ids.Count)
}
Write-Host "TOTAL_QUEUED=$queued"

Write-Host '=== 4) Poll until high-value uploaded count is low or 4h timeout ==='
$deadline = (Get-Date).AddHours(4)
$lastReady = -1
$stall = 0
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 60
  $headers = Get-AuthHeaders
  $d = (Invoke-RestMethod 'http://localhost:8000/api/v1/indexing/status' -Headers $headers).data
  $qa = (Invoke-RestMethod 'http://localhost:6333/collections/industrial_brain_chunks').result.points_count
  $pendingHV = docker exec industrial-brain-postgres-1 psql -U industrial_brain -d industrial_brain -t -A -c @"
SELECT count(*) FROM documents d
JOIN document_catalog c ON c.id = d.catalog_id
WHERE d.status = 'uploaded'
  AND (
    c.doc_category IN ('test_report','manual','maintenance','sop','safety','regulation','sensor','work_order')
    OR c.doc_category = 'datasheet'
  );
"@
  $pendingHV = [int]("$pendingHV".Trim())
  Write-Host ("[{0:HH:mm:ss}] ready={1} chunks={2} qdrant={3} high_value_uploaded_left={4} jobs={5}" -f `
    (Get-Date), $d.ready, $d.chunks, $qa, $pendingHV, ($d.jobs_by_status | ConvertTo-Json -Compress))

  # Stop when high-value pending (excluding uncapped datasheet leftovers beyond cap) is mostly done:
  # use id list membership for precise remaining
  $remainingExact = docker exec industrial-brain-postgres-1 psql -U industrial_brain -d industrial_brain -t -A -c @"
SELECT count(*) FROM documents WHERE status='uploaded' AND id IN (
  SELECT trim(both from x) FROM unnest(string_to_array(pg_read_file('/tmp/nope'), E'\n')) x
);
"@ 2>$null

  if ([int]$d.ready -eq $lastReady) { $stall++ } else { $stall = 0 }
  $lastReady = [int]$d.ready

  # Practical completion: fewer than 50 high-value core categories still uploaded
  $coreLeft = docker exec industrial-brain-postgres-1 psql -U industrial_brain -d industrial_brain -t -A -c @"
SELECT count(*) FROM documents d
JOIN document_catalog c ON c.id = d.catalog_id
WHERE d.status='uploaded'
  AND c.doc_category IN ('test_report','manual','maintenance','sop','safety','regulation','sensor','work_order');
"@
  $coreLeft = [int]("$coreLeft".Trim())
  if ($coreLeft -le 50 -and [int]($d.jobs_by_status.running | ForEach-Object { $_ }) -eq 0) {
    Write-Host "High-value core nearly complete (coreLeft=$coreLeft)."
    break
  }
  if ($stall -ge 20) {
    Write-Host "Progress stalled for ~20 min — continuing to verification with current state."
    break
  }
}

Write-Host '=== 5) Domain coverage + retrieval smoke ==='
docker exec industrial-brain-postgres-1 psql -U industrial_brain -d industrial_brain -c @"
SELECT COALESCE(c.metadata->>'asset_domain','?') AS domain,
       count(DISTINCT d.id) AS docs_chunked,
       count(ch.id) AS chunks
FROM documents d
JOIN document_catalog c ON c.id = d.catalog_id
LEFT JOIN document_chunks ch ON ch.document_id = d.id
WHERE d.status = 'chunked'
GROUP BY 1
ORDER BY 1;
"@

$headers = Get-AuthHeaders
$queries = @(
  @{ q = 'electric motor efficiency temperature rise'; label = 'Motors' },
  @{ q = 'centrifugal pump maintenance SOP'; label = 'Pumps' },
  @{ q = 'valve actuator inspection procedure'; label = 'Valves' },
  @{ q = 'oil refinery compressor seal maintenance'; label = 'Oil_Refineries' },
  @{ q = 'bearing lubrication schedule'; label = 'Bearings' }
)
foreach ($item in $queries) {
  try {
    $body = (@{ query = $item.q; limit = 3; persist_trace = $false } | ConvertTo-Json)
    $res = Invoke-RestMethod -Method Post -Uri 'http://localhost:8000/api/v1/indexing/retrieve' `
      -Headers $headers -Body $body -TimeoutSec 60
    $n = 0
    if ($res.data.results) { $n = @($res.data.results).Count }
    Write-Host ("RETRIEVE [{0}] hits={1}" -f $item.label, $n)
  } catch {
    Write-Host ("RETRIEVE [{0}] ERROR: {1}" -f $item.label, $_.Exception.Message)
  }
}

$d = (Invoke-RestMethod 'http://localhost:8000/api/v1/indexing/status' -Headers $headers).data
$qa = (Invoke-RestMethod 'http://localhost:6333/collections/industrial_brain_chunks').result.points_count
Write-Host '=== FINAL ==='
Write-Host ($d | ConvertTo-Json -Compress)
Write-Host "qdrant_points=$qa"
Write-Host 'FAILED JOB SAMPLE:'
docker exec industrial-brain-postgres-1 psql -U industrial_brain -d industrial_brain -c @"
SELECT left(error_message,120) AS err, count(*)
FROM indexing_jobs
WHERE status='failed'
GROUP BY 1 ORDER BY 2 DESC LIMIT 10;
"@
