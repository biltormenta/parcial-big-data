@echo off
rem Doble clic para subir a GitHub los cambios hechos y seguir el build de Jenkins.
rem Usa "ExecutionPolicy Bypass" para que PowerShell no bloquee el script.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0subir_cambios.ps1" %*
echo.
pause
