$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Join-Path $root 'backend'
$gaFrontendDir = Join-Path $root 'generative_agents\environment\frontend_server'
$pythonExe = 'C:\Users\Admin\miniconda3\python.exe'
$backendPort = 8000
$frontendPort = 8010

function Test-PortListening([int]$Port) {
  try {
    $conn = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction Stop
    return $null -ne $conn
  } catch {
    return $false
  }
}

function Stop-PortProcess([int]$Port) {
  try {
    $conns = Get-NetTCPConnection -LocalPort $Port -ErrorAction Stop
    $pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($pid in $pids) {
      if ($pid -and $pid -ne $PID) {
        try { Stop-Process -Id $pid -Force -ErrorAction Stop } catch {}
      }
    }
  } catch {}
}

function Wait-Http([string]$Url, [int]$TimeoutSec = 25) {
  $start = Get-Date
  while (((Get-Date) - $start).TotalSeconds -lt $TimeoutSec) {
    try {
      $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
      if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500) { return $true }
    } catch {}
    Start-Sleep -Milliseconds 600
  }
  return $false
}

function Test-HttpQuick([string]$Url, [int]$TimeoutSec = 4) {
  try {
    $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec
    return ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500)
  } catch {
    return $false
  }
}

if (-not (Test-Path $pythonExe)) { throw "Python not found at $pythonExe" }
if (-not (Test-Path (Join-Path $backendDir 'main.py'))) { throw "backend/main.py not found in $backendDir" }
if (-not (Test-Path (Join-Path $gaFrontendDir 'manage.py'))) { throw "manage.py not found in $gaFrontendDir" }

# 1) Backend API
if ((Test-PortListening $backendPort) -and (-not (Test-HttpQuick "http://127.0.0.1:$backendPort/api/state" 3))) {
  Stop-PortProcess $backendPort
  Start-Sleep -Milliseconds 600
}

if (-not (Test-PortListening $backendPort)) {
  $backendCmd = "`$env:TX_REAL_MODE='off'; `$env:SETTLEMENT_STRATEGY='off'; `$env:CIRCLE_POLL_ATTEMPTS='1'; & `"$pythonExe`" -m uvicorn main:app --host 127.0.0.1 --port $backendPort"
  Start-Process powershell -WorkingDirectory $backendDir -ArgumentList '-NoExit','-Command',$backendCmd | Out-Null
  Start-Sleep -Seconds 2
}

if (-not (Wait-Http "http://127.0.0.1:$backendPort/api/state" 90)) {
  throw "Backend API did not come up on port $backendPort"
}

# 2) Seed agents if empty
try {
  $state = Invoke-RestMethod -Uri "http://127.0.0.1:$backendPort/api/state" -Method Get -TimeoutSec 5
  $entityCount = 0
  if ($state -and $state.entities) {
    $entityCount = $state.entities.PSObject.Properties.Count
  }

  if ($entityCount -lt 10) {
    $spawnPlan = @(
      @{t='worker'; n=12},
      @{t='thief'; n=5},
      @{t='cop'; n=3},
      @{t='banker'; n=2},
      @{t='bank'; n=1}
    )
    foreach ($plan in $spawnPlan) {
      for ($i = 0; $i -lt $plan.n; $i++) {
        try {
          Invoke-RestMethod -Uri "http://127.0.0.1:$backendPort/api/spawn?entity_type=$($plan.t)&balance=5" -Method Post -TimeoutSec 4 | Out-Null
        } catch {}
      }
    }
  }
} catch {}

# 3) Smallville frontend in bridge mode
if ((Test-PortListening $frontendPort) -and (-not (Test-HttpQuick "http://127.0.0.1:$frontendPort/simulator_home" 3))) {
  Stop-PortProcess $frontendPort
  Start-Sleep -Milliseconds 600
}

if (-not (Test-PortListening $frontendPort)) {
  $frontendCmd = "`$env:SMALLVILLE_MODE='bridge'; `$env:SMALLVILLE_BRIDGE_URL='http://127.0.0.1:$backendPort/api/bridge/smallville'; `$env:SMALLVILLE_BRIDGE_STEP_ON_POLL='1'; & `"$pythonExe`" manage.py runserver 127.0.0.1:$frontendPort"
  Start-Process powershell -WorkingDirectory $gaFrontendDir -ArgumentList '-NoExit','-Command',$frontendCmd | Out-Null
  Start-Sleep -Seconds 2
}

if (-not (Wait-Http "http://127.0.0.1:$frontendPort/simulator_home" 90)) {
  if (-not (Test-PortListening $frontendPort)) {
    throw "Frontend did not come up on port $frontendPort"
  }
}

# 4) Open live map
$liveUrl = "http://127.0.0.1:$frontendPort/demo/bridge_smallville/0/2/"
Start-Process $liveUrl | Out-Null

Write-Host ''
Write-Host 'Bridge Smallville is running.'
Write-Host "Backend API:   http://127.0.0.1:$backendPort/api/state"
Write-Host "Live map URL:  $liveUrl"
Write-Host ''
Write-Host 'One-command launch complete.'
