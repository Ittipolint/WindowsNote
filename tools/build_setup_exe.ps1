[CmdletBinding()]
param(
    [switch]$Sign,
    [switch]$SignStrict
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Path $PSScriptRoot -Parent
$vendorRoot = Join-Path $repoRoot 'tools\vendor'
$nsisZip = Join-Path $vendorRoot 'nsis.zip'
$nsisRoot = Join-Path $vendorRoot 'nsis'
$makensis = Join-Path $nsisRoot 'nsis-3.11\makensis.exe'
$signingScript = Join-Path $repoRoot 'tools\signing.ps1'

if ($Sign) {
    . $signingScript
}

# Build app exe first
& (Join-Path $repoRoot 'tools\build_release.ps1') -Sign:$Sign -SignStrict:$SignStrict

if (-not (Test-Path $makensis)) {
    New-Item -ItemType Directory -Force -Path $vendorRoot | Out-Null

    Write-Host 'Downloading portable NSIS...'
    curl.exe -L "https://sourceforge.net/projects/nsis/files/NSIS%203/3.11/nsis-3.11.zip/download" -o $nsisZip | Out-Null

    if (Test-Path $nsisRoot) { Remove-Item -Recurse -Force $nsisRoot }
    Expand-Archive -Path $nsisZip -DestinationPath $nsisRoot -Force
}

if (-not (Test-Path $makensis)) {
    throw 'makensis.exe not found after setup.'
}

Push-Location $repoRoot
try {
    & $makensis /V2 (Join-Path $repoRoot 'installer\windowsnote.nsi')
    if ($LASTEXITCODE -ne 0) {
        throw "NSIS build failed with code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

$setupPath = Join-Path $repoRoot 'release\WindowsNote-Setup.exe'
if (-not (Test-Path $setupPath)) {
    throw 'Setup EXE was not generated.'
}

if ($Sign) {
    Invoke-CodeSigning -FilePath $setupPath -Strict:$SignStrict | Out-Null
}

Write-Host "Setup generated: $setupPath"
