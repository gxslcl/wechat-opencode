@echo off
title OpenCode Bridge
cd /d "%~dp0"

echo ============================================
echo   OpenCode Bridge (Feishu)
echo ============================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found - run setup first
    pause
    exit /b 1
)

if "%DEEPSEEK_API_KEY%"=="" (
    echo [WARNING] DEEPSEEK_API_KEY not set
    echo   The bot will start but commands may fail
    echo.
)

echo Starting service...
echo   Feishu Bot ready
echo   Console shows logs, auto-reload on code change
echo   Press Ctrl+C twice to stop
echo ============================================
echo.

:LOOP
.venv\Scripts\python.exe -m wechat_opencode --config config.yaml
echo.
echo   Service stopped. Restarting in 2 seconds...
timeout /t 2 /nobreak >nul
goto LOOP
