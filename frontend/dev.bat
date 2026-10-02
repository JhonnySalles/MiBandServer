@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo   Frontend - Instalando Dependencias
echo ==========================================
call yarn install

echo.
echo ==========================================
echo   Frontend - Iniciando Servidor Vite Dev
echo ==========================================
call yarn dev
