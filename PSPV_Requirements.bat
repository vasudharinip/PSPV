@echo off
setlocal enabledelayedexpansion

REM ============================================================
REM  PSPV Dependency Installer (Multi-Python Support)
REM ============================================================

echo.
echo Available Python versions (examples: 3.9, 3.11, 3.14)
set /p pyver=Enter the Python version you want to use: 

if "%pyver%"=="" (
    echo [ERROR] No version entered.
    goto :fail
)

echo.
echo [1/4] Checking Python %pyver% availability...

py -%pyver% --version >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python %pyver% is not installed or not accessible via "py".
    echo         Try running: py -0
    goto :fail
)

py -%pyver% --version

echo.
echo [2/4] Ensuring pip is up to date...
py -%pyver% -m pip install --upgrade pip

echo.
echo [3/4] Checking and installing required packages...

REM -------- Package List --------
set packages=numpy pandas matplotlib PyQt6 openpyxl xlrd scipy comtrade pssepath

for %%p in (%packages%) do (
    echo Checking %%p...

    py -%pyver% -m pip show %%p >nul 2>nul
    if errorlevel 1 (
        echo    Installing %%p...
        py -%pyver% -m pip install %%p
        if errorlevel 1 (
            echo [ERROR] Failed to install %%p
            goto :fail
        )
    ) else (
        echo    %%p already installed.
    )
)

echo.
echo ============================================================
echo  SETUP COMPLETE
echo ------------------------------------------------------------
echo  All required packages are installed for Python %pyver%.
echo ============================================================
echo.
pause
exit /b 0

:fail
echo.
echo ============================================================
echo  SETUP FAILED
echo ============================================================
pause
exit /b 1