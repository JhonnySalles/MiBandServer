@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

:: Ler portas do .env se existir
set BACKEND_PORT=8190
set FRONTEND_PORT=8090

if exist ".env" (
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        if /i "%%A"=="BACKEND_PORT" set BACKEND_PORT=%%B
        if /i "%%A"=="PORT" set BACKEND_PORT=%%B
        if /i "%%A"=="FRONTEND_PORT" set FRONTEND_PORT=%%B
    )
)

echo ====================================================
echo   MiBandServer - Iniciando Backend e Frontend
echo ====================================================

echo Iniciando Backend em uma nova janela na porta %BACKEND_PORT%...
start "MiBandServer - Backend" cmd /k "cd /d "%~dp0backend" && run.bat"

echo Iniciando Frontend em uma nova janela...
start "MiBandServer - Frontend" cmd /k "cd /d "%~dp0frontend" && dev.bat"

echo.
echo ====================================================
echo   Servicos iniciados em janelas separadas!
echo   Backend API: http://localhost:%BACKEND_PORT%
echo   Frontend:    http://localhost:5173 (Dev) ou http://localhost:%FRONTEND_PORT% (Prod)
echo ====================================================
echo.
pause
