param(
  # Zero-keys demo: forces simulated settlement (same as previous script behavior).
  [switch]$SimOnly
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Join-Path $root 'backend'
$gaFrontendDir = Join-Path $root 'generative_agents\environment\frontend_server'
$backendPythonCandidates = @(
  $env:AGENTIC_BACKEND_PYTHON_EXE,
  $env:AGENTIC_PYTHON_EXE,
  'C:\Python314\python.exe',
  'C:\Users\Admin\miniconda3\python.exe'
) | Where-Object { $_ -and $_.Trim() -ne '' }
$backendPythonExe = $backendPythonCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

$frontendPythonCandidates = @(
  $env:AGENTIC_FRONTEND_PYTHON_EXE,
  'C:\Users\Admin\miniconda3\python.exe',
  $backendPythonExe
) | Where-Object { $_ -and $_.Trim() -ne '' }
$frontendPythonExe = $frontendPythonCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
$backendPort = 8000
$frontendPort = 8010
$forceRestart = $true

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

function Stop-AgenticServerProcesses {
  $patterns = @(
    '*uvicorn*main:app*',
    '*manage.py runserver 127.0.0.1:8010*'
  )
  try {
    $procs = Get-CimInstance Win32_Process | Where-Object {
      $cmd = $_.CommandLine
      $cmd -and (($patterns | Where-Object { $cmd -like $_ }).Count -gt 0)
    }
    foreach ($p in $procs) {
      if ($p.ProcessId -and $p.ProcessId -ne $PID) {
        try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop } catch {}
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

if (-not (Test-Path $backendPythonExe)) { throw "Backend Python not found at $backendPythonExe" }
if (-not (Test-Path $frontendPythonExe)) { throw "Frontend Python not found at $frontendPythonExe" }
if (-not (Test-Path (Join-Path $backendDir 'main.py'))) { throw "backend/main.py not found in $backendDir" }
if (-not (Test-Path (Join-Path $gaFrontendDir 'manage.py'))) { throw "manage.py not found in $gaFrontendDir" }

# Fail fast if runtime interpreter does not have the Circle SDK import path.
$circleImport = & $backendPythonExe -c "from circle.web3 import developer_controlled_wallets as _dcw; print('ok')" 2>&1
if ($LASTEXITCODE -ne 0) {
  $reqPath = Join-Path $backendDir 'requirements.txt'
  throw "Circle SDK import check failed for $backendPythonExe. Install backend deps with: `"$backendPythonExe`" -m pip install -r `"$reqPath`". Details: $circleImport"
}

# 1) Backend API
Stop-AgenticServerProcesses
Start-Sleep -Milliseconds 700
if ($forceRestart -and (Test-PortListening $backendPort)) {
  Stop-PortProcess $backendPort
  Start-Sleep -Milliseconds 700
} elseif ((Test-PortListening $backendPort) -and (-not (Test-HttpQuick "http://127.0.0.1:$backendPort/api/state" 3))) {
  Stop-PortProcess $backendPort
  Start-Sleep -Milliseconds 600
}

if (-not (Test-PortListening $backendPort)) {
  if ($SimOnly) {
    # Sim-only: clamp after `.env` load in Python (see AGENTIC_SIM_ONLY in main.py / arc.py).
    $backendCmd = "`$env:AGENTIC_SIM_ONLY='1'; `$env:FORCE_SINGLE_TARGET='0'; `$env:AUTO_TICK_ENABLED='1'; `$env:AUTO_TICK_MS='100'; & `"$backendPythonExe`" -m uvicorn main:app --host 127.0.0.1 --port $backendPort"
  } else {
    # Normal mode: allow real settlement according to .env / runtime config.
    # AUTO_TICK_*: background sim loop in main.py — keep Django from also stepping every poll (see SMALLVILLE_BRIDGE_STEP_ON_POLL below).
    $backendCmd = "`$env:FORCE_SINGLE_TARGET='0'; `$env:AUTO_TICK_ENABLED='1'; `$env:AUTO_TICK_MS='100'; & `"$backendPythonExe`" -m uvicorn main:app --host 127.0.0.1 --port $backendPort"
  }
  Start-Process powershell -WorkingDirectory $backendDir -ArgumentList '-NoExit','-Command',$backendCmd | Out-Null
  Start-Sleep -Seconds 2
}

if (-not (Wait-Http "http://127.0.0.1:$backendPort/api/state" 90)) {
  throw "Backend API did not come up on port $backendPort"
}

# 1b) Prove this port is *this* repo’s FastAPI (not another app that also exposes /api/state).
$expectedRev = 'ae-smallville-lifetime-v2'
try {
  $mf = Invoke-RestMethod -Uri "http://127.0.0.1:$backendPort/api/bridge/manifest" -Method Get -TimeoutSec 6
  $rev = [string]$mf.bridge_revision
  if ($rev -ne $expectedRev) {
    throw "Bridge manifest revision mismatch: got '$rev', expected '$expectedRev'."
  }
} catch {
  throw ("Port $backendPort is listening but is not the AgenticEconomy bridge from this repo " +
    "(GET /api/bridge/manifest failed or wrong revision). Stop whatever owns the port, then re-run this script. Details: $_")
}

# 1c) API surface check: ensure this backend includes the latest tx session endpoint.
# If this fails, :8000 is likely an older checkout/process and reset behavior will be inconsistent.
try {
  $openapi = Invoke-RestMethod -Uri "http://127.0.0.1:$backendPort/openapi.json" -Method Get -TimeoutSec 6
  $paths = $openapi.paths
  if (-not $paths -or -not ($paths.PSObject.Properties.Name -contains "/api/tx/session/reset")) {
    throw "Missing /api/tx/session/reset route"
  }
} catch {
  throw ("Port $backendPort is serving an older backend API surface (missing /api/tx/session/reset). " +
    "Stop stale processes and restart from this repo. Details: $_")
}

# 2) Enforce stable demo population (prevents economy collapse from over-spawn)
try {
  $state = Invoke-RestMethod -Uri "http://127.0.0.1:$backendPort/api/state" -Method Get -TimeoutSec 5
  $entityCount = 0
  $roleCounts = @{
    worker = 0
    cop = 0
    banker = 0
    spy = 0
    thief = 0
    bank = 0
  }

  if ($state -and $state.entities) {
    $entities = @($state.entities.PSObject.Properties.Value)
    $entityCount = $entities.Count
    foreach ($e in $entities) {
      if (-not $e) { continue }
      $rawRole = [string]$e.persona_role
      $rawType = [string]$e.type
      $role = if ($rawRole -and $rawRole.Trim() -ne '') { $rawRole.ToLower() } else { $rawType.ToLower() }
      if ($roleCounts.ContainsKey($role)) { $roleCounts[$role] = [int]$roleCounts[$role] + 1 }
    }
  }

  $needsReset = (
    ($entityCount -ne 11) -or
    ($roleCounts.worker -ne 6) -or
    ($roleCounts.cop -ne 1) -or
    ($roleCounts.banker -ne 1) -or
    ($roleCounts.spy -ne 1) -or
    ($roleCounts.thief -ne 1) -or
    ($roleCounts.bank -ne 1)
  )

  if ($needsReset) {
    Invoke-RestMethod -Uri "http://127.0.0.1:$backendPort/api/demo/reset-economy" `
      -Method Post `
      -TimeoutSec 8 | Out-Null
    Write-Host "Population normalized to 6 workers, 1 cop, 1 banker, 1 spy, 1 thief, 1 bank."
  }
} catch {}

# 2.5) Default to role-hub mode (route disabled unless explicitly enabled)
try {
  $routePayload = @{
    sequence = @(
      @{ id = "B11"; anchor = "center" },
      @{ id = "B08"; anchor = "center" }
    )
    phase = 0
    stage = "entry"
    hold_ticks = 30
    max_stage_ticks = 220
    allow_stage_timeout = $false
    inside_stage_enabled = $false
    arrival_ratio = 1.0
    arrival_radius = 28
    enabled = $false
  } | ConvertTo-Json -Depth 4
  Invoke-RestMethod -Uri "http://127.0.0.1:$backendPort/api/route/set" `
    -Method Post `
    -ContentType "application/json" `
    -Body $routePayload `
    -TimeoutSec 8 | Out-Null
} catch {}

# 3) Smallville frontend in bridge mode
if ($forceRestart -and (Test-PortListening $frontendPort)) {
  Stop-PortProcess $frontendPort
  Start-Sleep -Milliseconds 700
} elseif ((Test-PortListening $frontendPort) -and (-not (Test-HttpQuick "http://127.0.0.1:$frontendPort/simulator_home" 3))) {
  Stop-PortProcess $frontendPort
  Start-Sleep -Milliseconds 600
}

if (-not (Test-PortListening $frontendPort)) {
  # STEP_ON_POLL=0: FastAPI already advances the world on AUTO_TICK_MS; stepping again on every browser poll causes jerky motion and double-speed sim.
  $frontendCmd = "`$env:SMALLVILLE_MODE='bridge'; `$env:SMALLVILLE_BRIDGE_URL='http://127.0.0.1:$backendPort/api/bridge/smallville'; `$env:SMALLVILLE_BRIDGE_STEP_ON_POLL='0'; & `"$frontendPythonExe`" manage.py runserver 127.0.0.1:$frontendPort"
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
