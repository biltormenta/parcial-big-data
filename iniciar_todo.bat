@echo off
rem Doble clic para levantar todo el sistema y dejar listo el webhook.
rem Usa "ExecutionPolicy Bypass" para que PowerShell no bloquee el script.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0iniciar_todo.ps1" %*
echo.
echo El script termino. Si cerraste los tuneles, vuelve a ejecutarlo para obtener una URL nueva.
pause
