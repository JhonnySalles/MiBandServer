@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ==========================================
echo   Backend - Verificando Ambiente Python
echo ==========================================

if not exist ".venv\Scripts\activate.bat" (
    echo Criando ambiente virtual .venv...
    python -m venv .venv
)

echo Ativando ambiente virtual...
call .venv\Scripts\activate.bat

echo ==========================================
echo   Backend - Instalando Dependencias
echo ==========================================
pip install -r requirements.txt

:: Definir porta padrão caso não definida no .env
set BACKEND_PORT=8190
if exist "..\.env" (
    for /f "usebackq tokens=1,* delims==" %%A in ("..\.env") do (
        if /i "%%A"=="BACKEND_PORT" set BACKEND_PORT=%%B
        if /i "%%A"=="PORT" set BACKEND_PORT=%%B
    )
)

echo.
echo ==========================================
echo   Backend - Iniciando FastAPI na Porta %BACKEND_PORT%
echo ==========================================
uvicorn app.main:app --host 0.0.0.0 --port %BACKEND_PORT% --reload
