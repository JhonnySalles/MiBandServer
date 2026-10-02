@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo   Frontend - Instalando Dependencias (Yarn)
echo ==========================================
call yarn install

echo ==========================================
echo   Frontend - Compilando Projeto (Build)
echo ==========================================
call yarn build

if %ERRORLEVEL% equ 0 (
    echo.
    echo Build concluido com sucesso na pasta 'dist'!
) else (
    echo.
    echo Ocorreu um erro durante o build do frontend.
)

pause
