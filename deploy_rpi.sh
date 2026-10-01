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
    echo " -> Arquivo .env não encontrado. Criando padrão..."
    cat <<EOF > .env
FRONTEND_PORT=8080
VITE_API_URL=http://localhost:8000
EOF
fi

# 3. Construir e iniciar os contêineres Docker
echo "[2/3] Construindo contêineres Docker..."
docker compose build

echo "[3/3] Iniciando serviços em segundo plano..."
docker compose up -d

echo ""
echo "========================================="
echo " Servidor MiBand 6 inicializado com sucesso!"
echo " Acesse o painel web em: http://<IP_DO_RASPBERRY>:8080"
echo "========================================="
