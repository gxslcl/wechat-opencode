# Run WeChat-OpenCode in development mode (foreground)

$ProjectDir = "C:\Users\1\wechat-opencode"
$venvPython = "$ProjectDir\.venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "Virtual environment not found. Run setup.ps1 first." -ForegroundColor Red
    exit 1
}

Write-Host "Starting WeChat-OpenCode in development mode..." -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop." -ForegroundColor Yellow
Write-Host ""

& $venvPython -m wechat_opencode --config "$ProjectDir\config.yaml"
