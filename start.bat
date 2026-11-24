@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  python -c "import sys; sys.exit(sys.version_info < (3,11))" >nul 2>nul
  if errorlevel 1 goto :python_error
  python -m venv .venv
  if errorlevel 1 goto :setup_error
)
set "PY=.venv\Scripts\python.exe"
if /i "%ALLN1_AUTO_UPDATE%"=="0" goto :source_update_done
if /i "%ALLN1_AUTO_UPDATE%"=="false" goto :source_update_done
"%PY%" scripts\update_source.py
:source_update_done
fc /b requirements.txt ".venv\installed-requirements.txt" >nul 2>nul
if errorlevel 1 (
  echo Installing release dependencies into .venv ...
  "%PY%" -m pip install --disable-pip-version-check -r requirements.txt
  if errorlevel 1 goto :setup_error
  "%PY%" -m pip check
  if errorlevel 1 goto :setup_error
  copy /y requirements.txt ".venv\installed-requirements.txt" >nul
  if errorlevel 1 goto :setup_error
)
if /i "%~1"=="--setup-only" exit /b 0
"%PY%" app.py
if errorlevel 1 goto :run_error
exit /b 0
:python_error
echo Install Python 3.11 or newer and make sure python is on PATH.
goto :failure
:setup_error
echo Setup failed. Check the installer output and your connection, then run again.
goto :failure
:run_error
echo Startup failed. Check the error above. If the port is busy, close the other instance.
:failure
if /i "%~1"=="--setup-only" exit /b 1
pause
exit /b 1
