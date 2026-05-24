# WeChat-OpenCode Service Installer
# Uses NSSM to run the Python service as a Windows background service

param(
    [switch]$DryRun = $false
)

$ServiceName = "WeChatOpenCode"
$ProjectDir = "C:\Users\1\wechat-opencode"
$PythonExe = "C:\Users\1\AppData\Local\Programs\Python\Python312\python.exe"
$LogFile = "$ProjectDir\service.log"

function Write-Step {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Cyan
}

function Write-Error {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

function Write-Success {
    param([string]$Message)
    Write-Host "[OK] $Message" -ForegroundColor Green
}

# Check admin rights
$IsAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $IsAdmin -and -not $DryRun) {
    Write-Error "This script requires Administrator privileges. Please run as Administrator."
    Write-Host "Right-click PowerShell and select 'Run as Administrator', then run this script again."
    exit 1
}

# Check if NSSM is available
$nssmPath = Get-Command "nssm" -ErrorAction SilentlyContinue
if (-not $nssmPath) {
    Write-Step "NSSM not found. Checking alternative locations..."
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
    if ($DryRun) {
        Write-Step "[DRY RUN] Would download NSSM from https://nssm.cc/release/nssm-2.24.zip"
    } else {
        Write-Step "Downloading NSSM..."
        $nssmUrl = "https://nssm.cc/release/nssm-2.24.zip"
        $zipPath = "$env:TEMP\nssm-2.24.zip"
        $extractPath = "$env:TEMP\nssm"

        try {
            Invoke-WebRequest -Uri $nssmUrl -OutFile $zipPath -ErrorAction Stop
            Expand-Archive -Path $zipPath -DestinationPath $extractPath -Force
            $nssmDir = Get-ChildItem -Path $extractPath -Directory | Select-Object -First 1
            $nssmPath = Join-Path $nssmDir.FullName "win64\nssm.exe"
            $installDir = "$env:ProgramFiles\nssm"
            New-Item -ItemType Directory -Path $installDir -Force | Out-Null
            Copy-Item -Path $nssmPath -Destination "$installDir\nssm.exe" -Force
            $nssmPath = "$installDir\nssm.exe"
            Write-Success "NSSM installed to $nssmPath"
        } catch {
            Write-Error "Failed to download/install NSSM: $_"
            Write-Host "Please install NSSM manually: https://nssm.cc/download"
            exit 1
        }
    }
}

if ($DryRun) {
    Write-Step "[DRY RUN] Would configure service:"
    Write-Step "  Service Name: $ServiceName"
    Write-Step "  Executable: $PythonExe"
    Write-Step "  Arguments: -m wechat_opencode"
    Write-Step "  Working Dir: $ProjectDir"
    Write-Step "  Environment: WOC_CONFIG=$ProjectDir\config.yaml"
    Write-Step "  Auto-start: yes"
    Write-Step "  Restart on failure: yes (5s delay)"
    Write-Step "  Log file: $LogFile"
    Write-Step "[DRY RUN] Complete. No changes made."
    exit 0
}

Write-Step "Installing service '$ServiceName'..."

# Check if service already exists
$existingService = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existingService) {
    Write-Step "Service already exists. Stopping and removing..."
    Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
    & $nssmPath remove $ServiceName confirm
    Start-Sleep -Seconds 2
}

# Install the service
& $nssmPath install $ServiceName $PythonExe
& $nssmPath set $ServiceName AppParameters "-m wechat_opencode"
& $nssmPath set $ServiceName AppDirectory $ProjectDir
& $nssmPath set $ServiceName AppEnvironmentExtra "WOC_CONFIG=$ProjectDir\config.yaml"
& $nssmPath set $ServiceName Start SERVICE_AUTO_START
& $nssmPath set $ServiceName AppStdout $LogFile
& $nssmPath set $ServiceName AppStderr $LogFile
& $nssmPath set $ServiceName AppRotateFiles 1
& $nssmPath set $ServiceName AppRotateOnline 1
& $nssmPath set $ServiceName AppRotateSeconds 86400
& $nssm_path set $ServiceName AppRestartDelay 5000

Write-Step "Starting service..."
Start-Service -Name $ServiceName
Start-Sleep -Seconds 3

# Verify service is running
$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($svc -and $svc.Status -eq 'Running') {
    Write-Success "Service '$ServiceName' is installed and running."
    Write-Success "Log file: $LogFile"
} else {
    Write-Error "Service installed but may not be running. Check status:"
    Write-Host "  Get-Service $ServiceName"
    Write-Host "  Check log: Get-Content '$LogFile' -Tail 20"
}

Write-Step "Installation complete."
