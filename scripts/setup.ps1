# WeChat-OpenCode Project Setup Script
# Creates virtual environment, installs dependencies, and configures the project

param(
    [switch]$DryRun = $false
)

$ProjectDir = "C:\Users\1\wechat-opencode"

function Write-Step {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Message)
    Write-Host "[OK] $Message" -ForegroundColor Green
}

function Write-Error {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

if ($DryRun) {
    Write-Step "[DRY RUN] Would run full setup for $ProjectDir"
    Write-Step "  Steps: create venv -> pip install requirements -> pip install -e . -> copy config"
    exit 0
}

Write-Step "Setting up WeChat-OpenCode project..."

# Verify project directory exists
if (-not (Test-Path $ProjectDir)) {
    Write-Error "Project directory $ProjectDir not found."
    exit 1
}

# Create virtual environment
$venvPath = "$ProjectDir\.venv"
if (-not (Test-Path $venvPath)) {
    Write-Step "Creating virtual environment..."
    & "C:\Users\1\AppData\Local\Programs\Python\Python312\python.exe" -m venv $venvPath
    Write-Success "Virtual environment created at $venvPath"
} else {
    Write-Step "Virtual environment already exists at $venvPath"
}

# Activate and install
$pip = "$venvPath\Scripts\pip.exe"
if (-not (Test-Path $pip)) {
    $pip = "$venvPath\Scripts\python.exe" -m pip
}

Write-Step "Installing requirements..."
& $pip install --upgrade pip
& $pip install -r "$ProjectDir\requirements.txt"
& $pip install -e "$ProjectDir"

# Copy config if not exists
$configFile = "$ProjectDir\config.yaml"
$configExample = "$ProjectDir\config.example.yaml"
if (-not (Test-Path $configFile) -and (Test-Path $configExample)) {
    Write-Step "Copying config.example.yaml to config.yaml..."
    Copy-Item -Path $configExample -Destination $configFile
    Write-Success "Config file created. Edit config.yaml to customize."
} elseif (Test-Path $configFile) {
    Write-Step "Config file already exists."
}

# Verify installation
Write-Step "Verifying installation..."
$python = "$venvPath\Scripts\python.exe"
$result = & $python -c "import wechat_opencode; print(wechat_opencode.__version__)" 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Success "Package installed successfully (version: $result)"
} else {
    Write-Error "Package import failed: $result"
}

Write-Success "Setup complete!"
Write-Step ""
Write-Step "Next steps:"
Write-Step "  1. Edit config.yaml to configure your settings"
Write-Step "  2. Run .venv\Scripts\python -m wechat_opencode --check to verify"
Write-Step "  3. Run scripts\install_service.ps1 to install as Windows service (Admin)"
Write-Step "  4. Or run scripts\run_dev.ps1 to start in foreground for testing"
