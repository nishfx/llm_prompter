@echo off
REM ------------------------------------------------------------
REM  PromptBuilder – one‑file build script (RC‑1, PATCH 2)
REM ------------------------------------------------------------

setlocal enabledelayedexpansion
set APP_NAME=PromptBuilder

REM ——— 1.  move to project root ————————————————————————————
cd /d "%~dp0.."
set "PROJECT_ROOT=%CD%"
echo Project root detected as: %PROJECT_ROOT%

REM ——— 2.  clean old build artefacts ——————————————————————
if exist dist  (echo Removing existing dist…  & rmdir /s /q dist )
if exist build (echo Removing existing build… & rmdir /s /q build )

REM ——— 3.  locate & activate Poetry venv ——————————————
for /f "tokens=*" %%i in ('poetry env info --path 2^>nul') do set "VENV_PATH=%%i"
if not defined VENV_PATH (
    echo ERROR: Poetry virtualenv not found.  Run "poetry install" first.
    exit /b 1
)
if not exist "%VENV_PATH%" (
    echo ERROR: venv path does not exist → %VENV_PATH%
    exit /b 1
)
call "%VENV_PATH%\Scripts\activate.bat"

where pyinstaller >nul 2>nul
if %errorlevel% neq 0 (
    echo ERROR: pyinstaller not on PATH after venv activation.
    exit /b 1
)

REM ——— 4.  run PyInstaller ————————————————————————————
set "SPEC_FILE=%PROJECT_ROOT%\scripts\freeze.spec"
echo Using spec file: %SPEC_FILE%
pyinstaller "%SPEC_FILE%"
if %errorlevel% neq 0 (
    echo Build failed (PyInstaller exit code %errorlevel%).
    exit /b 1
)

REM ——— 5.  verify output EXE ————————————————————————————
set "EXE_PATH=%PROJECT_ROOT%\dist\%APP_NAME%.exe"
if not exist "%EXE_PATH%" (
    echo ERROR: Expected output "%EXE_PATH%" not found.
    exit /b 1
)
echo Build successful – created: %EXE_PATH%

REM ——— 6.  package EXE into zip ————————————————————————
cd dist
set "ARCHIVE=..\%APP_NAME%_Windows.zip"

where powershell >nul 2>nul
if %errorlevel% equ 0 (
    powershell -NoLogo -NoProfile -Command "Compress-Archive -Path '%APP_NAME%.exe' -DestinationPath '%ARCHIVE%' -Force"
    echo Created %ARCHIVE% with PowerShell
) else (
    where 7z >nul 2>nul
    if %errorlevel% equ 0 (
        7z a "%ARCHIVE%" "%APP_NAME%.exe"
        echo Created %ARCHIVE% with 7‑Zip
    ) else (
        echo NOTE: PowerShell/7‑Zip not found – skipping zip step.
    )
)
cd ..

echo Build process finished.
exit /b 0
