[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Path $PSScriptRoot -Parent
$distRoot = Join-Path $repoRoot 'dist'
$buildRoot = Join-Path $repoRoot 'build'
$releaseRoot = Join-Path $repoRoot 'release'
$payloadRoot = Join-Path $releaseRoot 'payload'

if (Test-Path $distRoot) { Remove-Item -Path $distRoot -Recurse -Force }
if (Test-Path $buildRoot) { Remove-Item -Path $buildRoot -Recurse -Force }
if (Test-Path $releaseRoot) { Remove-Item -Path $releaseRoot -Recurse -Force }

Write-Host 'Building WindowsNote.exe via PyInstaller...'
python -m PyInstaller --noconfirm --windowed --onefile --name WindowsNote "$repoRoot\src\windows_note.py"

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
