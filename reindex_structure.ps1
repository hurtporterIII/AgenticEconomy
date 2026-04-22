$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = 'C:\Users\Admin\miniconda3\python.exe'
$scriptPath = Join-Path $root 'generate_structure.py'

if (-not (Test-Path $pythonExe)) { throw "Python not found at $pythonExe" }
if (-not (Test-Path $scriptPath)) { throw "generate_structure.py not found at $scriptPath" }

& $pythonExe $scriptPath --root $root

Write-Host "Reindex complete."
