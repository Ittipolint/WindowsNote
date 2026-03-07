[CmdletBinding()]
param(
    [switch]$Sign,
    [switch]$SignStrict
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Path $PSScriptRoot -Parent
$distRoot = Join-Path $repoRoot 'dist'
$buildRoot = Join-Path $repoRoot 'build'
$releaseRoot = Join-Path $repoRoot 'release'
$payloadRoot = Join-Path $releaseRoot 'payload'
$signingScript = Join-Path $repoRoot 'tools\signing.ps1'

if ($Sign) {
    . $signingScript
}

if (Test-Path $distRoot) { Remove-Item -Path $distRoot -Recurse -Force }
if (Test-Path $buildRoot) { Remove-Item -Path $buildRoot -Recurse -Force }
New-Item -ItemType Directory -Path $releaseRoot -Force | Out-Null
if (Test-Path $payloadRoot) { Remove-Item -Path $payloadRoot -Recurse -Force }
foreach ($artifact in @('Install-WindowsNote.ps1', 'WindowsNote-payload.zip', 'WindowsNote-Setup.exe', 'WindowsNote-Setup.sed')) {
    $artifactPath = Join-Path $releaseRoot $artifact
    if (Test-Path $artifactPath) {
        Remove-Item -Path $artifactPath -Force -ErrorAction SilentlyContinue
    }
}

Write-Host 'Building WindowsNote.exe via PyInstaller...'
python -m PyInstaller --noconfirm --windowed --onefile --name WindowsNote "$repoRoot\src\windows_note.py"

if ($Sign) {
    Invoke-CodeSigning -FilePath (Join-Path $distRoot 'WindowsNote.exe') -Strict:$SignStrict | Out-Null
}

New-Item -ItemType Directory -Path $payloadRoot -Force | Out-Null
Copy-Item -Path (Join-Path $distRoot 'WindowsNote.exe') -Destination (Join-Path $payloadRoot 'WindowsNote.exe') -Force
Copy-Item -Path (Join-Path $repoRoot 'config.json') -Destination (Join-Path $payloadRoot 'config.json') -Force
Copy-Item -Path (Join-Path $repoRoot 'README.md') -Destination (Join-Path $payloadRoot 'README.md') -Force

Copy-Item -Path (Join-Path $repoRoot 'installer\Install-WindowsNote.ps1') -Destination (Join-Path $releaseRoot 'Install-WindowsNote.ps1') -Force

Compress-Archive -Path "$payloadRoot\*" -DestinationPath (Join-Path $releaseRoot 'WindowsNote-payload.zip') -Force

Write-Host ''
Write-Host 'Build completed.'
Write-Host "Payload:  $releaseRoot\WindowsNote-payload.zip"
Write-Host "Installer: $releaseRoot\Install-WindowsNote.ps1"
Write-Host ''
Write-Host 'Usage:'
Write-Host "1) Extract payload zip into same folder as Install-WindowsNote.ps1"
Write-Host "2) Run: powershell -ExecutionPolicy Bypass -File .\Install-WindowsNote.ps1"
