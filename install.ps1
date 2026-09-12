[CmdletBinding()]
param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "Programs\kvpn"),
    [string]$SourceBaseUrl = "https://raw.githubusercontent.com/seo-rii/kaist-openconnect/main"
)

$ErrorActionPreference = "Stop"

function Write-Info([string]$Message) {
    Write-Host "==> $Message" -ForegroundColor Blue
}

if ($env:OS -ne "Windows_NT") {
    throw "install.ps1 supports Windows only. Use install.sh on macOS or Linux."
}

$Python = Get-Command py -ErrorAction SilentlyContinue
if (-not $Python) {
    $Python = Get-Command python -ErrorAction SilentlyContinue
}
if (-not $Python) {
    throw "Python 3 was not found. Install it from https://www.python.org/downloads/windows/ and rerun this script."
}

$OpenConnect = Get-Command openconnect.exe -ErrorAction SilentlyContinue
if (-not $OpenConnect) {
    $OpenConnectCandidates = @(
        (Join-Path $env:ProgramFiles "OpenConnect\openconnect.exe"),
        (Join-Path $env:ProgramFiles "OpenConnect-GUI\openconnect.exe")
    )
    if ($env:ProgramW6432) {
        $OpenConnectCandidates += Join-Path $env:ProgramW6432 "OpenConnect\openconnect.exe"
    }
    if (${env:ProgramFiles(x86)}) {
        $OpenConnectCandidates += Join-Path ${env:ProgramFiles(x86)} "OpenConnect\openconnect.exe"
        $OpenConnectCandidates += Join-Path ${env:ProgramFiles(x86)} "OpenConnect-GUI\openconnect.exe"
    }
    $OpenConnect = $OpenConnectCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $OpenConnect) {
    throw "OpenConnect was not found. Download and install the official Windows build from https://gitlab.com/openconnect/openconnect/-/jobs/artifacts/v9.21/download?job=MinGW64%2FGnuTLS and rerun this script."
}

Write-Info "Installing kvpn to $InstallDir"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

$CheckoutDir = if ($MyInvocation.MyCommand.Path) {
    Split-Path -Parent $MyInvocation.MyCommand.Path
} else {
    ""
}
$CheckoutKvpn = if ($CheckoutDir) { Join-Path $CheckoutDir "kvpn" } else { "" }
$CheckoutLauncher = if ($CheckoutDir) { Join-Path $CheckoutDir "kvpn.cmd" } else { "" }
$DestinationKvpn = Join-Path $InstallDir "kvpn"
$DestinationLauncher = Join-Path $InstallDir "kvpn.cmd"

if ($CheckoutDir -and (Test-Path $CheckoutKvpn) -and (Test-Path $CheckoutLauncher)) {
    Copy-Item -Force $CheckoutKvpn $DestinationKvpn
    Copy-Item -Force $CheckoutLauncher $DestinationLauncher
} else {
    Invoke-WebRequest "$SourceBaseUrl/kvpn" -OutFile $DestinationKvpn
    Invoke-WebRequest "$SourceBaseUrl/kvpn.cmd" -OutFile $DestinationLauncher
}

$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
$PathParts = @($UserPath -split ";" | Where-Object { $_ })
if ($PathParts -notcontains $InstallDir) {
    $NewUserPath = (($PathParts + $InstallDir) -join ";")
    [Environment]::SetEnvironmentVariable("Path", $NewUserPath, "User")
    Write-Info "Added $InstallDir to your user PATH."
}
if (($env:Path -split ";") -notcontains $InstallDir) {
    $env:Path = "$InstallDir;$env:Path"
}

& $DestinationLauncher --help | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "kvpn was installed, but its Python launcher check failed."
}

Write-Info "Done. Open an Administrator PowerShell and run: kvpn"
