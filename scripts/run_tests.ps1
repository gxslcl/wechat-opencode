# Run WeChat-OpenCode tests

$ProjectDir = "C:\Users\1\wechat-opencode"
$venvPython = "$ProjectDir\.venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    # Fall back to system Python
    $venvPython = "C:\Users\1\AppData\Local\Programs\Python\Python312\python.exe"
}

Write-Host "Running tests..." -ForegroundColor Cyan
& $venvPython -m pytest "$ProjectDir\tests\" -v
