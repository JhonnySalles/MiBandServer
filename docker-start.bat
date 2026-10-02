@echo off
setlocal
cd /d "%~dp0"

echo ====================================================
echo   MiBandServer - Build e Inicializacao dos Containers
echo ====================================================

echo 1. Construindo e subindo os containers Docker...
docker compose up -d --build

if %ERRORLEVEL% equ 0 (
    echo.
    echo ====================================================
    echo   Containers iniciados com sucesso!
    echo ====================================================
    docker compose ps
    echo.
    echo Para acompanhar os logs em tempo real, execute:
    echo   docker compose logs -f
) else (
    echo.
    echo [ERRO] Falha ao construir ou iniciar os containers.
)

echo.
pause
