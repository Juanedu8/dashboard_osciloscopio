@echo off
cd /d "%~dp0"
echo Iniciando emulador del SBC y dashboard HTTP en este computador...
python demo_integracion.py
if errorlevel 1 (
  echo.
  echo Si Python no esta disponible, prueba: py demo_integracion.py
  pause
)
