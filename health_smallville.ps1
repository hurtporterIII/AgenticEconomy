$ErrorActionPreference = 'Stop'

$backend = 'http://127.0.0.1:8000'
$frontend = 'http://127.0.0.1:8010'
$bridgeEndpoint = "$backend/api/bridge/smallville"
$manifestEndpoint = "$backend/api/bridge/manifest"
$expectedBridgeRev = 'ae-smallville-lifetime-v2'

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
$manifestOk = Test-Url $manifestEndpoint
$frontOk = Test-Url "$frontend/demo/bridge_smallville/0/2/"

Write-Host ("- Backend state:      " + ($(if ($stateOk) {'OK'} else {'FAIL'})))
Write-Host ("- Bridge manifest:    " + ($(if ($manifestOk) {'OK'} else {'FAIL'})))
Write-Host ("- Bridge endpoint:    " + ($(if ($bridgeOk) {'OK'} else {'FAIL'})))
Write-Host ("- Frontend route:     " + ($(if ($frontOk) {'OK'} else {'FAIL'})))

if (-not ($stateOk -and $bridgeOk -and $manifestOk -and $frontOk)) {
  throw "Endpoint health check failed."
}

try {
  $mf = Invoke-RestMethod -Uri $manifestEndpoint -Method Get -TimeoutSec 8
  if ([string]$mf.bridge_revision -ne $expectedBridgeRev) {
    throw ("Wrong API on $backend — bridge_revision is '" + [string]$mf.bridge_revision + "', expected '$expectedBridgeRev'.")
  }
  Write-Host ("- Bridge code path:   " + [string]$mf.endpoints_py)
} catch {
  throw "Bridge manifest check failed: $_"
}

Write-Host "Checking Arc / settlement diagnostics..."
try {
  $diag = Invoke-RestMethod -Uri "$backend/api/tx/diagnostics" -Method Get -TimeoutSec 8
  $strat = [string]$diag.settlement.strategy
  $rm = [string]$diag.config.real_mode
  $hasKey = [bool]$diag.config.has_circle_api_key
  $hasEnt = [bool]$diag.config.has_entity_secret
  $hasWa = [bool]$diag.config.has_wallet_address
  $hasDst = [bool]$diag.config.has_destination_address
  $realN = [int]$diag.diagnostics.real_tx_count
  $simN = [int]$diag.diagnostics.simulated_tx_count
  Write-Host ("  SETTLEMENT_STRATEGY: " + $strat)
  Write-Host ("  TX_REAL_MODE:        " + $rm)
  Write-Host ("  Circle env complete: " + ($(if ($hasKey -and $hasEnt -and $hasWa -and $hasDst) {'YES'} else {'NO'})))
  Write-Host ("  Real / sim tx count: " + $realN + " / " + $simN)
  if ($strat -eq 'off' -or $rm -eq 'off') {
    Write-Host "  (Arc settlement disabled or sim-only — use .env or omit -SimOnly on start script.)"
  }
} catch {
  Write-Host "  WARN: could not read /api/tx/diagnostics: $_"
}

Write-Host "Checking movement signal..."

$snap1 = Get-BridgeSnapshot
if (-not [string]$snap1.world.bridge_revision) {
  throw "Bridge JSON missing world.bridge_revision — port $backend is not running this repo's FastAPI (restart backend from AgenticEconomy/backend)."
}
if ([string]$snap1.world.bridge_revision -ne $expectedBridgeRev) {
  throw ("Bridge revision mismatch on smallville payload: '" + [string]$snap1.world.bridge_revision + "'")
}
$w1 = $snap1.actors | Where-Object { $_.id -eq 'worker_1' } | Select-Object -First 1
if (-not $w1 -or ($null -eq $w1.PSObject.Properties['lifetime_collected'])) {
  throw "Bridge actors missing lifetime_collected — stale FastAPI build on $backend."
}
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

Write-Host "Checking role visibility and home anchoring..."
$roles = @{}
foreach ($a in $snap2.actors) {
  $r = [string]$a.role
  if (-not $roles.ContainsKey($r)) { $roles[$r] = 0 }
  $roles[$r] += 1
}
$hasSpy = $roles.ContainsKey("spy")
$hasThief = $roles.ContainsKey("thief")
Write-Host ("- Spy present:         " + ($(if ($hasSpy) {'YES'} else {'NO'})))
Write-Host ("- Thief present:       " + ($(if ($hasThief) {'YES'} else {'NO'})))
if (-not $hasSpy) { throw "Spy missing from bridge payload." }
if (-not $hasThief) { throw "Thief missing from bridge payload." }

$bankerOutOfHome = @()
foreach ($a in $snap2.actors | Where-Object { $_.role -eq "banker" }) {
  $dz = [string]$a.dest_zone
  if ($dz -notmatch "Bank Home") { $bankerOutOfHome += $a.id }
}
Write-Host ("- Banker home-anchored: " + ($(if ($bankerOutOfHome.Count -eq 0) {'YES'} else {'NO'})))
if ($bankerOutOfHome.Count -gt 0) {
  throw ("Banker not home-anchored: " + ($bankerOutOfHome -join ", "))
}

Write-Host ""
Write-Host "Smallville health check PASSED."
