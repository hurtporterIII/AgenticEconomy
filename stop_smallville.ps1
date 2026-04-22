$ErrorActionPreference = 'SilentlyContinue'

$ports = @(8000, 8010)

function Stop-PortProcess([int]$Port) {
  try {
    $conns = Get-NetTCPConnection -LocalPort $Port
    $pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($pid in $pids) {
      if ($pid -and $pid -ne $PID) {
        try { Stop-Process -Id $pid -Force } catch {}
      }
    }
  } catch {}
}

foreach ($p in $ports) { Stop-PortProcess $p }

Write-Host "Stopped Smallville services on ports: $($ports -join ', ')"
