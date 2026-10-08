@echo off
rem Loggy launcher for Windows.
rem The first run sets up a private Python environment in the .venv folder;
rem after that it just starts the logbook. Arguments are passed on to Loggy,
rem for example:  loggy.bat export C:\Users\me\Documents\logbook.csv
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Setting up Loggy for the first time. This takes a minute...
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3 -m venv .venv
    ) else (
        python -m venv .venv
    )
)
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo Loggy needs Python 3.9 or newer. Install it from
    echo https://www.python.org/downloads/ and tick "Add python.exe to PATH",
    echo then run loggy.bat again.
    pause
    exit /b 1
)

rem Install or update the requirements whenever requirements.txt changes.
fc /b requirements.txt ".venv\requirements.txt" >nul 2>nul
if errorlevel 1 (
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --quiet -r requirements.txt
    if errorlevel 1 (
        echo.
        echo Could not install what Loggy needs. Check your internet connection
        echo and run loggy.bat again.
        pause
        exit /b 1
    )
    copy /y requirements.txt ".venv\requirements.txt" >nul
)

".venv\Scripts\python.exe" -m loggy %*
if errorlevel 1 pause
