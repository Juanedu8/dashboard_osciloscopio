@echo off
cd /d "%~dp0"
python server.py
if errorlevel 1 (
  echo.
  echo Comprueba que Python este instalado y agregado al PATH.
  pause
)
