# Install ai-study into the user-level skills directory.
# NOTE: keep this file as UTF-8 with BOM, or PowerShell 5.1 reads non-ASCII as garbage.
$ErrorActionPreference = 'Stop'
$src = Join-Path $PSScriptRoot 'ai-study'
$dst = Join-Path $env:USERPROFILE '.agents\skills\ai-study'

# Gate 1: placeholder residue (« » left over from authoring) must be zero.
Write-Host '[1/2] placeholder check' -ForegroundColor Cyan
python (Join-Path $PSScriptRoot 'tools\check_placeholders.py') $src
if ($LASTEXITCODE -ne 0) {
  Write-Host 'ABORT: placeholder residue in source.' -ForegroundColor Red
  exit 1
}

# Gate 2: regression suite must pass. A guard that is never tested is not a guard.
Write-Host '[2/2] regression suite' -ForegroundColor Cyan
python (Join-Path $PSScriptRoot 'tools\test.py')
if ($LASTEXITCODE -ne 0) {
  Write-Host 'ABORT: regression tests failed, not installing.' -ForegroundColor Red
  exit 1
}

if (Test-Path $dst) { Remove-Item -Recurse -Force $dst }
New-Item -ItemType Directory -Force -Path (Split-Path $dst) | Out-Null
Copy-Item -Recurse -Force $src $dst
Write-Output "installed -> $dst"
Get-ChildItem -Recurse -File $dst | ForEach-Object { $_.FullName.Substring($dst.Length + 1) }