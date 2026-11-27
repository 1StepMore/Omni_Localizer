# Self-sufficient bootstrap for THIS repo (Omni_Localizer) — no suite checkout
# required (OL#228). Independent mode: THIS repo's uv.lock / pyproject only.
# The joint mode (suite-root uv.lock) is documented in AGENTS.md.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/setup_dev.ps1
#   powershell -ExecutionPolicy Bypass -File scripts/setup_dev.ps1 -CheckOnly
param([switch]$CheckOnly)

$ErrorActionPreference = 'Stop'
Set-Location (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) '..')

function Write-Info { param([string]$m) Write-Host "[INFO] $m" }
function Write-Ok2  { param([string]$m) Write-Host "[OK]   $m" }
function Write-Err2 { param([string]$m) Write-Host "[ERR]  $m" }

if (Get-Command uv -ErrorAction SilentlyContinue) {
    if ($CheckOnly) { Write-Ok2 "CHECK-ONLY: uv found; sync skipped."; exit 0 }
    Write-Info "uv found — uv sync --all-extras (independent mode: this repo's uv.lock)"
    uv sync --all-extras
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Info "Self-check:"
    uv run python -c "import ol_md; from importlib.metadata import version; print('OK: ol_md', version('omni-localizer'), 'importable')"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Ok2 "Omni_Localizer ready. CLI smoke: `$env:OMNI_TEST_FAKE_LLM='1'; uv run ol translate-md <md> -s en -t zh -o <dir>"
    exit 0
}

# venv + pip path (no uv installed) — mirrors the suite's setup_dev.ps1 shape.
$PythonExe = $null
foreach ($candidate in @('python', 'py')) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($cmd) { $PythonExe = $cmd.Source; break }
}
if (-not $PythonExe) {
    Write-Err2 "Neither uv nor Python found. Install Python >= 3.13 or uv."
    exit 1
}

$VersionRaw = & $PythonExe -c "import sys; print('%d.%d' % sys.version_info[:2])"
$Parts = $VersionRaw.Trim().Split('.')
if ([int]$Parts[0] -lt 3 -or ([int]$Parts[0] -eq 3 -and [int]$Parts[1] -lt 13)) {
    Write-Err2 "Python >= 3.13 required, got $VersionRaw"
    exit 1
}
if ($CheckOnly) { Write-Ok2 "CHECK-ONLY: Python $VersionRaw found (no uv); venv creation skipped."; exit 0 }

if (-not (Test-Path '.venv')) { & $PythonExe -m venv .venv }
$Vpy = if (Test-Path '.venv\Scripts\python.exe') { '.venv\Scripts\python.exe' } else { '.venv\bin\python' }
& $Vpy -m pip install --upgrade pip | Out-Null
& $Vpy -m pip install -e .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Info "Self-check:"
& $Vpy -c "import ol_md; from importlib.metadata import version; print('OK: ol_md', version('omni-localizer'), 'importable')"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Ok2 "Omni_Localizer ready. CLI smoke: `$env:OMNI_TEST_FAKE_LLM='1'; .venv\Scripts\ol.exe translate-md <md> -s en -t zh -o <dir>"
