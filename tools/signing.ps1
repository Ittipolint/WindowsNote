[CmdletBinding()]
param()

function Get-SignToolPath {
    if ($env:SIGNTOOL_PATH -and (Test-Path $env:SIGNTOOL_PATH)) {
        return $env:SIGNTOOL_PATH
    }

    $cmd = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    $kitsRoot = "${env:ProgramFiles(x86)}\Windows Kits\10\bin"
    if (-not (Test-Path $kitsRoot)) {
        return $null
    }

    $candidates = Get-ChildItem -Path $kitsRoot -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -like "*\x64\signtool.exe" } |
        Sort-Object FullName -Descending
    if ($candidates.Count -gt 0) {
        return $candidates[0].FullName
    }
    return $null
}

function Invoke-CodeSigning {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [switch]$Strict
    )

    if (-not (Test-Path $FilePath)) {
        throw "Signing target not found: $FilePath"
    }

    $signtool = Get-SignToolPath
    if (-not $signtool) {
        $msg = "signtool.exe not found. Install Windows SDK or set SIGNTOOL_PATH."
        if ($Strict) { throw $msg } else { Write-Warning $msg; return $false }
    }

    $timestampUrl = if ($env:CODE_SIGN_TIMESTAMP_URL) { $env:CODE_SIGN_TIMESTAMP_URL } else { "http://timestamp.digicert.com" }
    $args = @("sign", "/fd", "SHA256", "/td", "SHA256", "/tr", $timestampUrl)

    if ($env:CODE_SIGN_PFX) {
        if (-not (Test-Path $env:CODE_SIGN_PFX)) {
            $msg = "CODE_SIGN_PFX path not found: $env:CODE_SIGN_PFX"
            if ($Strict) { throw $msg } else { Write-Warning $msg; return $false }
        }
        $args += @("/f", $env:CODE_SIGN_PFX)
        if ($env:CODE_SIGN_PASSWORD) {
            $args += @("/p", $env:CODE_SIGN_PASSWORD)
        }
    }
    elseif ($env:CODE_SIGN_SUBJECT) {
        $args += @("/n", $env:CODE_SIGN_SUBJECT)
    }
    else {
        $msg = "Missing signing identity. Set CODE_SIGN_PFX (and CODE_SIGN_PASSWORD) or CODE_SIGN_SUBJECT."
        if ($Strict) { throw $msg } else { Write-Warning $msg; return $false }
    }

    $args += $FilePath
    & $signtool @args
    if ($LASTEXITCODE -ne 0) {
        $msg = "Code signing failed for: $FilePath"
        if ($Strict) { throw $msg } else { Write-Warning $msg; return $false }
    }

    Write-Host "Signed: $FilePath"
    return $true
}

