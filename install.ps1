#Requires -Version 5.1
param([switch]$DependenciesOnly)
$AniCliRef = if ($env:ANI_CLI_REF) { $env:ANI_CLI_REF } else { "v5.1" }
$AniCliDir = Join-Path $env:LOCALAPPDATA "anilixy\bin"
$ProjectDir = $PSScriptRoot

function Info($message) { Write-Host "[INFO] $message" -ForegroundColor Green }
function Warn($message) { Write-Host "[WARN] $message" -ForegroundColor Yellow }
function Step($message) { Write-Host "[STEP] $message" -ForegroundColor Blue }
function Fail($message) {
    Write-Host "[ERR] $message" -ForegroundColor Red
    exit 1
}

function Has($command) {
    return $null -ne (Get-Command $command -ErrorAction SilentlyContinue)
}

function Refresh-Path {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

function Find-Python {
    $candidates = @("py -3.14", "py -3.13", "py -3.12", "py -3.11", "py -3.10", "python", "python3")
    foreach ($candidate in $candidates) {
        $parts = $candidate -split " "
        if (-not (Has $parts[0])) { continue }
        $arguments = @($parts | Select-Object -Skip 1)
        $check = "import sys, sysconfig; print((3, 10) <= sys.version_info[:2] <= (3, 14) and sysconfig.get_platform() == 'win-amd64')"
        $result = & $parts[0] @arguments -c $check 2>$null
        if ($LASTEXITCODE -eq 0 -and $result -eq "True") { return ,$parts }
    }
    return $null
}

function Install-Package($command, $scoopName, $wingetId) {
    if (Has $command) {
        Info "$command is already installed"
        return
    }
    Step "Installing $command..."
    if (Has "scoop") {
        if ($scoopName -like "extras/*") { scoop bucket add extras 2>$null | Out-Null }
        scoop install $scoopName
    } elseif (Has "winget") {
        winget install --id $wingetId --exact --accept-source-agreements --accept-package-agreements
    } else {
        Fail "Neither Scoop nor winget was found. Install $command by hand and run this again."
    }
    Refresh-Path
    if (-not (Has $command)) {
        Warn "$command is not on PATH yet. Open a new terminal before running anilixy."
    }
}

function Install-AniCli {
    if (Has "ani-cli") {
        Info "ani-cli is already installed"
        return
    }
    $script = Join-Path $AniCliDir "ani-cli"
    if (Test-Path $script) {
        Info "ani-cli is already installed at $script (update it with: ani-cli -U)"
        return
    }

    Step "Installing ani-cli $AniCliRef from the official repository..."
    New-Item -ItemType Directory -Force -Path $AniCliDir -ErrorAction Stop | Out-Null
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $url = "https://raw.githubusercontent.com/pystardust/ani-cli/$AniCliRef/ani-cli"
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $script -ErrorAction Stop
    } catch {
        Fail "Could not download ani-cli: $_"
    }
    Info "ani-cli installed at $script"
}

function Install-Anilixy($python) {
    $interpreter = $python[0]
    $arguments = @($python | Select-Object -Skip 1)

    & $interpreter @arguments -m pipx --version 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Step "Installing pipx..."
        & $interpreter @arguments -m pip install --user pipx
        if ($LASTEXITCODE -ne 0) { Fail "Could not install pipx." }
    }

    Step "Installing anilixy..."
    & $interpreter @arguments -m pipx install --force $ProjectDir
    if ($LASTEXITCODE -ne 0) { Fail "Could not install anilixy." }

    $reply = Read-Host "Add PDF support for light novels? [y/N]"
    if ($reply -match "^[Yy]") {
        & $interpreter @arguments -m pipx inject anilixy pymupdf
        if ($LASTEXITCODE -ne 0) { Warn "Could not add PDF support." }
    }

    & $interpreter @arguments -m pipx ensurepath | Out-Null
}

if (-not $DependenciesOnly -and -not (Test-Path (Join-Path $ProjectDir "pyproject.toml"))) {
    Fail "pyproject.toml not found next to install.ps1."
}

$python = if ($DependenciesOnly) { $null } else { Find-Python }
if (-not $DependenciesOnly -and $null -eq $python) {
    Fail "No 64-bit Python 3.10-3.14 was found. Install Python 3.14 from https://www.python.org/downloads/ (it can sit beside other versions) and run this again."
}

Install-Package "git" "git" "Git.Git"
Install-Package "mpv" "extras/mpv" "shinchiro.mpv"
Install-Package "fzf" "fzf" "junegunn.fzf"
Install-AniCli
if ($DependenciesOnly) {
    Info "Done. Close this window and run anilixy.exe"
} else {
    Install-Anilixy $python
    Info "Done. Open a new terminal and run: anilixy"
}
Info "For images, use Windows Terminal 1.22+ or a WezTerm nightly build."
