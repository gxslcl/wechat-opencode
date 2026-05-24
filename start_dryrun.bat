@echo off
title WeChat-OpenCode Bridge [DRY-RUN]
cd /d "%~dp0"

echo ============================================
echo   WeChat-OpenCode Bridge — DRY RUN MODE
echo   ============================================
echo.
echo   This mode skips WeChat connection and
echo   opencode serve — good for testing the
echo   startup flow only.
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found.
    pause
    exit /b 1
)

echo [STEP] Running in dry-run mode...
echo.
.venv\Scripts\python.exe -m wechat_opencode --dry-run

echo.
echo [INFO] Dry-run finished.
pause
