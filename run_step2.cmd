@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" "%~dp0step2.py" %*
) else (
  py -3.12 "%~dp0step2.py" %*
)
exit /b %errorlevel%
