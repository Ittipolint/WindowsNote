[CmdletBinding()]
param(
    [string]$InstallDir = "$env:LOCALAPPDATA\WindowsNote",
    [switch]$NoShortcut
)

$ErrorActionPreference = 'Stop'

function Ensure-Directory {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        New-Item -Path $Path -ItemType Directory -Force | Out-Null
    }
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$payloadZip = Join-Path $scriptDir 'WindowsNote-payload.zip'
$stagingDir = Join-Path $env:TEMP ('WindowsNote_Install_' + [guid]::NewGuid().ToString('N'))

if (-not (Test-Path $payloadZip)) {
    throw "Missing payload zip: $payloadZip"
}

Ensure-Directory -Path $stagingDir
Expand-Archive -Path $payloadZip -DestinationPath $stagingDir -Force

$exeSource = Join-Path $stagingDir 'WindowsNote.exe'
$configSource = Join-Path $stagingDir 'config.json'
$readmeSource = Join-Path $stagingDir 'README.md'

if (-not (Test-Path $exeSource)) {
    throw 'WindowsNote.exe not found in payload zip.'
}

Ensure-Directory -Path $InstallDir
Copy-Item -Path $exeSource -Destination (Join-Path $InstallDir 'WindowsNote.exe') -Force

# Set default local storage under user profile, independent from install path.
$dataRoot = Join-Path $env:USERPROFILE 'Documents\WindowsNoteData'
$newConfig = @{
    data_root = $dataRoot
} | ConvertTo-Json -Depth 4
Set-Content -Path (Join-Path $InstallDir 'config.json') -Value $newConfig -Encoding utf8

if (Test-Path $readmeSource) {
    Copy-Item -Path $readmeSource -Destination (Join-Path $InstallDir 'README.md') -Force
}

if (-not $NoShortcut) {
    $wshShell = New-Object -ComObject WScript.Shell

    $desktopShortcutPath = Join-Path ([Environment]::GetFolderPath('Desktop')) 'WindowsNote.lnk'
    $desktopShortcut = $wshShell.CreateShortcut($desktopShortcutPath)
    $desktopShortcut.TargetPath = (Join-Path $InstallDir 'WindowsNote.exe')
    $desktopShortcut.WorkingDirectory = $InstallDir
    $desktopShortcut.Description = 'WindowsNote'
    $desktopShortcut.Save()

    $startMenuDir = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
    Ensure-Directory -Path $startMenuDir
    $startMenuShortcutPath = Join-Path $startMenuDir 'WindowsNote.lnk'
    $startMenuShortcut = $wshShell.CreateShortcut($startMenuShortcutPath)
    $startMenuShortcut.TargetPath = (Join-Path $InstallDir 'WindowsNote.exe')
    $startMenuShortcut.WorkingDirectory = $InstallDir
    $startMenuShortcut.Description = 'WindowsNote'
    $startMenuShortcut.Save()
}

Remove-Item -Path $stagingDir -Recurse -Force

Write-Host "WindowsNote installed successfully to: $InstallDir"
Write-Host "Data folder: $dataRoot"
