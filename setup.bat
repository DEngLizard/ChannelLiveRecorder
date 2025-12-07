@echo off
setlocal ENABLEDELAYEDEXPANSION

echo ============================================
echo    ChannelLiveRecorder - Windows Setup
echo ============================================
echo.

REM Repo root (folder where this script lives)
set "REPO_ROOT=%~dp0"
REM Remove trailing backslash if present on some shells (usually already OK)
if "%REPO_ROOT:~-1%"=="\" set "REPO_ROOT=%REPO_ROOT:~0,-1%"

set "VENV_PATH=%REPO_ROOT%\.venv"

echo Detecting Python...
where py >nul 2>nul
if %ERRORLEVEL%==0 (
    set "PYTHON=py"
) else (
    where python >nul 2>nul
    if %ERRORLEVEL%==0 (
        set "PYTHON=python"
    ) else (
        echo.
        echo [ERROR] No Python interpreter found.
        echo Install Python 3 and make sure "python" or "py" is on PATH.
        exit /b 1
    )
)

echo Using Python command: %PYTHON%
echo.

echo --------------------------------------------
echo Creating or reusing virtual environment
echo --------------------------------------------

if exist "%VENV_PATH%" (
    echo Reusing existing venv at "%VENV_PATH%"
) else (
    echo Creating new venv at "%VENV_PATH%"...
    %PYTHON% -m venv "%VENV_PATH%"
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Failed to create virtual environment.
        exit /b 1
    )
)

set "VENV_PYTHON=%VENV_PATH%\Scripts\python.exe"

if not exist "%VENV_PYTHON%" (
    echo [ERROR] venv Python not found at "%VENV_PYTHON%".
    exit /b 1
)

echo.
echo Python inside venv:
"%VENV_PYTHON%" --version
echo.

echo --------------------------------------------
echo Upgrading pip, wheel, setuptools
echo --------------------------------------------
"%VENV_PYTHON%" -m pip install --upgrade pip wheel setuptools
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Failed to upgrade pip/wheel/setuptools.
    exit /b 1
)

echo --------------------------------------------
echo Installing ChannelLiveRecorder dependencies
echo --------------------------------------------
"%VENV_PYTHON%" -m pip install "yt-dlp[default]" colorama PyYAML
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Failed to install Python dependencies.
    exit /b 1
)

echo --------------------------------------------
echo Checking for Deno (JS runtime for yt-dlp)
echo --------------------------------------------
where deno >nul 2>nul
if %ERRORLEVEL%==0 (
    for /f "usebackq delims=" %%A in (`deno --version ^| findstr /R "^deno "`) do (
        echo Deno detected: %%A
    )
) else (
    echo [WARN] Deno not found on PATH.
    echo        For best YouTube support, install Deno from:
    echo        https://deno.land/
    echo.
)

echo.
echo ============================================
echo Setup complete!
echo ============================================
echo.
echo To activate the virtual environment in this repo:
echo.
echo   call .venv\Scripts\activate
echo.
echo Then to start the recorder helper:
echo.
echo   python live-recording-helper.py
echo.
echo With cookies:
echo.
echo   python live-recording-helper.py --cookies %%USERPROFILE%%\ChannelLiveRecorder\cookies.txt
echo.
echo To test a single channel recorder directly:
echo.
echo   python recorder\live_stream_recorder.py SomeChannel .\output --cookies %%USERPROFILE%%\ChannelLiveRecorder\cookies.txt
echo.
echo ============================================

endlocal
