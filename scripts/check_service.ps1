# Check WeChat-OpenCode Service Status

$ServiceName = "WeChatOpenCode"

function Write-Step {
    param([string]$Message)
    Write-Host $Message
}

Write-Step "=== WeChat-OpenCode Service Status ==="
Write-Step ""

# Check service
$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($svc) {
    Write-Step "Service: $ServiceName"
    Write-Step "  Status: $($svc.Status)"
    Write-Step "  StartType: $($svc.StartType)"
} else {
    Write-Step "Service '$ServiceName' is not installed."
}

Write-Step ""

# Check process
$proc = Get-Process -Name "python*" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*wechat_opencode*" }
if ($proc) {
    Write-Step "Python process running: $($proc.Id)"
} else {
    Write-Step "No wechat_opencode Python process found."
}

Write-Step ""

# Check last 10 log lines
$logFile = "C:\Users\1\wechat-opencode\service.log"
if (Test-Path $logFile) {
    Write-Step "Last 10 log lines ($logFile):"
    Get-Content $logFile -Tail 10 -ErrorAction SilentlyContinue | ForEach-Object { Write-Step "  $_" }
} else {
    Write-Step "No log file found at $logFile"
}

Write-Step ""
Write-Step "=== End ==="
