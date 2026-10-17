@echo off
setlocal
if "%~1"=="" (
  echo Usage: run_step1.cmd "D:\Concerts\morceau_360.mp4"
  exit /b 2
)
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" "%~dp0step1.py" --source "%~1" --output "%~dp0outputs" --confirm-equirectangular
) else (
  py -3 "%~dp0step1.py" --source "%~1" --output "%~dp0outputs" --confirm-equirectangular
)
exit /b %errorlevel%
