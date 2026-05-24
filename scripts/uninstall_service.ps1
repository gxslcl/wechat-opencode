# Uninstall WeChat-OpenCode Windows Service

param(
    [switch]$DryRun = $false
)

$ServiceName = "WeChatOpenCode"

function Write-Step {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Message)
    Write-Host "[OK] $Message" -ForegroundColor Green
}

$IsAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $IsAdmin -and -not $DryRun) {
    Write-Host "This script requires Administrator privileges." -ForegroundColor Red
    exit 1
}

$nssmPath = Get-Command "nssm" -ErrorAction SilentlyContinue
if (-not $nssmPath) {
    $nssmCandidates = @(
        "$env:ProgramFiles\nssm\nssm.exe",
        "${env:ProgramFiles(x86)}\nssm\nssm.exe",
        "$env:LOCALAPPDATA\nssm\nssm.exe"
    )
    foreach ($candidate in $nssmCandidates) {
        if (Test-Path $candidate) {
            $nssmPath = $candidate
            break
        }
    }
}

if (-not $nssmPath) {
    Write-Host "NSSM not found. Stopping and removing service manually..." -ForegroundColor Yellow
    if (-not $DryRun) {
        Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
        sc.exe delete $ServiceName
        Write-Success "Service removed."
    } else {
        Write-Step "[DRY RUN] Would stop and remove service"
    }
    exit 0
}

if ($DryRun) {
    Write-Step "[DRY RUN] Would stop and remove service '$ServiceName'"
    exit 0
}

Write-Step "Stopping service '$ServiceName'..."
Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

Write-Step "Removing service..."
& $nssmPath remove $ServiceName confirm

Write-Success "Service '$ServiceName' has been removed."
