$ErrorActionPreference = 'Stop'

$backend = 'http://127.0.0.1:8000'
$frontend = 'http://127.0.0.1:8010'
$bridgeEndpoint = "$backend/api/bridge/smallville"

function Test-Url([string]$Url) {
  try {
    $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
    return ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500)
  } catch {
    return $false
  }
}

function Get-BridgeSnapshot() {
  return Invoke-RestMethod -Uri $bridgeEndpoint -Method Get -TimeoutSec 8
}

function Invoke-Step([int]$Count = 1) {
  for ($i = 0; $i -lt $Count; $i++) {
    try {
      Invoke-RestMethod -Uri "$backend/api/step" -Method Post -TimeoutSec 5 | Out-Null
    } catch {}
    Start-Sleep -Milliseconds 350
  }
}

Write-Host "Checking endpoints..."

$stateOk = Test-Url "$backend/api/state"
$bridgeOk = Test-Url $bridgeEndpoint
$frontOk = Test-Url "$frontend/demo/bridge_smallville/0/2/"

Write-Host ("- Backend state:      " + ($(if ($stateOk) {'OK'} else {'FAIL'})))
Write-Host ("- Bridge endpoint:    " + ($(if ($bridgeOk) {'OK'} else {'FAIL'})))
Write-Host ("- Frontend route:     " + ($(if ($frontOk) {'OK'} else {'FAIL'})))

if (-not ($stateOk -and $bridgeOk -and $frontOk)) {
  throw "Endpoint health check failed."
}

Write-Host "Checking movement signal..."

$snap1 = Get-BridgeSnapshot
$tick1 = [int]($snap1.world.tick)
$actors1 = @{}
foreach ($a in ($snap1.actors | Where-Object { $_.id })) {
  $actors1[$a.id] = @{ x = [double]$a.x; y = [double]$a.y; action = [string]$a.action }
}

Invoke-Step -Count 3

$snap2 = Get-BridgeSnapshot
$tick2 = [int]($snap2.world.tick)
$moved = 0
$changedAction = 0

foreach ($a in ($snap2.actors | Where-Object { $_.id })) {
  if (-not $actors1.ContainsKey($a.id)) { continue }
  $old = $actors1[$a.id]
  $dx = [math]::Abs(([double]$a.x) - $old.x)
  $dy = [math]::Abs(([double]$a.y) - $old.y)
  if (($dx + $dy) -gt 1.0) { $moved += 1 }
  if ([string]$a.action -ne $old.action) { $changedAction += 1 }
}

Write-Host "- Tick advanced:      $tick1 -> $tick2"
Write-Host "- Actors moved:       $moved"
Write-Host "- Action changes:     $changedAction"

if ($tick2 -le $tick1) {
  throw "Simulation tick did not advance."
}

if ($moved -lt 1 -and $changedAction -lt 1) {
  throw "No movement/action changes detected in sample window."
}

Write-Host ""
Write-Host "Smallville health check PASSED."
