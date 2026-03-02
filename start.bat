@echo off
setlocal ENABLEDELAYEDEXPANSION

set "REPO_ROOT=%~dp0"
if "%REPO_ROOT:~-1%"=="\" set "REPO_ROOT=%REPO_ROOT:~0,-1%"

set "VENV_PY=%REPO_ROOT%\.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
  echo [ERROR] venv not found. Run setup.bat first.
  exit /b 1
)

if not exist "%REPO_ROOT%\logs" mkdir "%REPO_ROOT%\logs" >nul 2>nul

echo [info] Updating yt-dlp + deps...
"%VENV_PY%" -m pip install -U pip wheel setuptools >nul
"%VENV_PY%" -m pip install -U "yt-dlp[default]" requests Pillow PyYAML colorama >nul

REM If user didn't pass cookie args, offer a simple interactive choice.
set "HAS_COOKIE=0"
for %%A in (%*) do (
  if "%%~A"=="--cookies-from-browser" set "HAS_COOKIE=1"
  if "%%~A"=="--cookies" set "HAS_COOKIE=1"
)

set "EXTRA_ARGS=%*"

if "%HAS_COOKIE%"=="0" (
  echo.
  echo Cookie mode:
  echo   1) none (try without cookies)
  echo   2) firefox
  echo   3) chrome
  echo   4) edge
  echo   5) chromium
  set /p CHOICE="Choose [1-5] (default 1): "
  if "!CHOICE!"=="" set "CHOICE=1"
  if "!CHOICE!"=="2" set "EXTRA_ARGS=--cookies-from-browser firefox %*"
  if "!CHOICE!"=="3" set "EXTRA_ARGS=--cookies-from-browser chrome %*"
  if "!CHOICE!"=="4" set "EXTRA_ARGS=--cookies-from-browser edge %*"
  if "!CHOICE!"=="5" set "EXTRA_ARGS=--cookies-from-browser chromium %*"
)

echo.
echo [info] Starting helper (auto-restart on crash). Logs: %REPO_ROOT%\logs

:loop
"%VENV_PY%" "%REPO_ROOT%\live_recording_helper.py" %EXTRA_ARGS%
set "EXITCODE=%ERRORLEVEL%"
echo [warn] Helper exited with code %EXITCODE%. Restarting in 5s...
timeout /t 5 /nobreak >nul
goto loop
