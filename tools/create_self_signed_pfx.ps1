[CmdletBinding()]
param(
    [string]$Subject = "WindowsNote Dev Code Signing",
    [string]$Password = "P@ssw0rd123!",
    [int]$ValidYears = 2,
    [string]$OutputDir = ".\tools\certs",
    [switch]$InstallToTrustedPublisher
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Path $PSScriptRoot -Parent
$outDir = if ([System.IO.Path]::IsPathRooted($OutputDir)) { $OutputDir } else { Join-Path $repoRoot $OutputDir }
New-Item -Path $outDir -ItemType Directory -Force | Out-Null

$safeName = ($Subject -replace '[^a-zA-Z0-9\-_. ]', '') -replace '\s+', '-'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$pfxPath = Join-Path $outDir ("$safeName-$stamp.pfx")
$cerPath = Join-Path $outDir ("$safeName-$stamp.cer")

Write-Host "Creating self-signed code-signing certificate..."
$cert = New-SelfSignedCertificate `
    -Type CodeSigningCert `
    -Subject "CN=$Subject" `
    -CertStoreLocation "Cert:\CurrentUser\My" `
    -KeyAlgorithm RSA `
    -KeyLength 3072 `
    -HashAlgorithm SHA256 `
    -KeyExportPolicy Exportable `
    -NotAfter (Get-Date).AddYears($ValidYears)

$securePassword = ConvertTo-SecureString -String $Password -Force -AsPlainText
Export-PfxCertificate -Cert $cert -FilePath $pfxPath -Password $securePassword | Out-Null
Export-Certificate -Cert $cert -FilePath $cerPath | Out-Null

if ($InstallToTrustedPublisher) {
    Write-Host "Installing certificate into CurrentUser TrustedPublisher and Root stores for local trust..."
    Import-Certificate -FilePath $cerPath -CertStoreLocation "Cert:\CurrentUser\TrustedPublisher" | Out-Null
    Import-Certificate -FilePath $cerPath -CertStoreLocation "Cert:\CurrentUser\Root" | Out-Null
}

Write-Host ""
Write-Host "Done."
Write-Host "PFX: $pfxPath"
Write-Host "CER: $cerPath"
Write-Host "Thumbprint: $($cert.Thumbprint)"
Write-Host ""
Write-Host "Use for build signing (PowerShell):"
Write-Host ('$env:CODE_SIGN_PFX="' + $pfxPath + '"')
Write-Host ('$env:CODE_SIGN_PASSWORD="' + $Password + '"')
Write-Host "powershell -ExecutionPolicy Bypass -File .\\tools\\build_setup_exe.ps1 -Sign -SignStrict"
