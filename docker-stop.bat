@echo off
setlocal
cd /d "%~dp0"

echo ====================================================
echo   MiBandServer - Parando Containers Docker
echo ====================================================

docker compose down

echo.
echo Containers finalizados.
pause
