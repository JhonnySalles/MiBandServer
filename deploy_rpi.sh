#!/bin/bash
# Script de validação e inicialização no Raspberry Pi

echo "========================================="
echo "   Iniciando MiBand 6 Server no RPi 4   "
echo "========================================="

# 1. Verificar serviço Bluetooth no host
echo "[1/3] Verificando status do Bluetooth..."
if systemctl is-active --quiet bluetooth; then
    echo " -> Bluetooth do host está ATIVO."
else
    echo " -> AVISO: Bluetooth do host inativo. Tentando iniciar..."
    sudo systemctl start bluetooth
fi

# 2. Carregar variáveis de ambiente
if [ ! -f .env ]; then
    echo " -> Arquivo .env não encontrado. Copiando de .env.example..."
    cp .env.example .env
fi

# Extrair porta do frontend do .env para exibição amigável
FRONTEND_PORT=$(grep -E '^FRONTEND_PORT=' .env | cut -d '=' -f2)
FRONTEND_PORT=${FRONTEND_PORT:-8090}

BACKEND_PORT=$(grep -E '^BACKEND_PORT=' .env | cut -d '=' -f2)
BACKEND_PORT=${BACKEND_PORT:-8190}

# 3. Construir e iniciar os contêineres Docker
echo "[2/3] Construindo contêineres Docker..."
docker compose build

echo "[3/3] Iniciando serviços em segundo plano..."
docker compose up -d

echo ""
echo "========================================="
echo " Servidor MiBand 6 inicializado com sucesso!"
echo " Painel Web: http://<IP_DO_RASPBERRY>:${FRONTEND_PORT}"
echo " API Backend: http://<IP_DO_RASPBERRY>:${BACKEND_PORT}"
echo "========================================="
