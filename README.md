# MiBand 6 Server - Hub para Raspberry Pi 4

O **MiBand 6 Server** é um sistema completo em Docker desenvolvido para conectar, monitorar e interagir com pulseiras **Xiaomi Mi Smart Band 6** via Bluetooth Low Energy (BLE). Ele foi otimizado para rodar de forma autônoma e eficiente em um Raspberry Pi 4.

---

## 🌟 Principais Funcionalidades

O projeto foi construído em duas fases principais de arquitetura e funcionalidades:

### Fase 1: Arquitetura Base
- **Sincronização BLE:** Leitura de passos, distância, batimentos cardíacos, calorias e nível de bateria diretamente da pulseira.
- **Integração Básica de Clima:** Envio de previsão do tempo manual ou automática via Open-Meteo.
- **Painel Dashboard Web:** Uma interface moderna, responsiva (Dark/Glassmorphism) para visualização de métricas e gráficos.
- **Sincronização Agendada:** Configuração de horários específicos para que o Raspberry Pi execute a sincronização com a pulseira em background.

### Fase 2: Evolução de Infraestrutura e Gestão
- **Suporte a Múltiplos Dispositivos:** O sistema agora é capaz de gerenciar múltiplas pulseiras Mi Band 6 cadastradas, cada uma com seus próprios horários e configurações de clima.
- **Banco de Dados em Memória (Redis):** O cache de APIs de clima e o estado transitório do servidor agora ficam em memória RAM. Isso **reduz drasticamente o desgaste de gravação no cartão SD** do Raspberry Pi, aumentando a vida útil do hardware.
- **Migrations de Banco de Dados:** Implementação do **Alembic** acoplado ao SQLModel, permitindo a evolução e controle seguro do esquema do banco de dados relacional.
- **Integrações Premium de Clima:** Suporte parametrizado via Tokens para obter a previsão do tempo de APIs precisas, como:
  - Open-Meteo (Gratuito)
  - OpenWeatherMap
  - WeatherAPI

---

## 🛠️ Stack Tecnológica

### Backend (Python)
- **FastAPI:** API de alta performance para comunicação com o frontend.
- **SQLModel (SQLite) + Alembic:** ORM moderno aliado a migrations versionadas.
- **Bleak:** Biblioteca assíncrona para comunicação via Bluetooth (BLE).
- **APScheduler:** Gerenciador de tarefas assíncronas para as sincronizações automáticas baseadas em cronogramas diários.
- **Redis:** Banco de dados e cache em memória.

### Frontend (Web)
- **Vite + TypeScript:** Ambiente de build veloz e tipagem estática.
- **Vanilla CSS:** Design system sob medida focado em estética premium, animações suaves e glassmorphism.
- **Chart.js:** Gráficos interativos para histórico de passos e frequência cardíaca.

### Infraestrutura
- **Docker Compose:** Orquestração de 3 containers (Backend, Frontend/Nginx e Redis).

---

## 🚀 Como Executar

### 1. Pré-requisitos
- **Raspberry Pi 4** (ou qualquer ambiente Linux com suporte a Bluetooth/Bluez)
- **Docker** e **Docker Compose** instalados

### 2. Configuração de Ambiente
Na raiz do projeto, você encontrará (ou deve criar) um arquivo `.env` para customizar as variáveis do sistema:

```env
# Porta onde o painel web estará acessível (útil para não conflitar com outros sites no RPi)
FRONTEND_PORT=8080

# Endereço da API do Backend (use localhost ou o IP do Raspberry Pi na sua rede local)
VITE_API_URL=http://localhost:8000
```

### 3. Inicialização com Docker
No terminal do Raspberry Pi, dentro da pasta do projeto, execute:

```bash
docker compose up --build -d
```
> O container de Backend necessita de parâmetros como `network_mode: "host"` e mapeamento do `/var/run/dbus` para utilizar o barramento Bluetooth real da máquina hospedeira.

---

## 📱 Telas do Painel de Controle

O sistema é dividido em abas intuitivas:

1. **Dashboard (Painel de Métricas):** Visualização imediata dos dados da pulseira primária através do cache do Redis, incluindo gráficos, bateria atual e opções rápidas de sincronizar/enviar clima.
2. **Histórico:** Tabela com todos os registros, logs de sucesso e erros das tentativas de sincronização com as pulseiras.
3. **Gerenciador de Dispositivos:** Um painel focado em descobrir pulseiras próximas através de um *Scanner Bluetooth*, permitindo o cadastro de Endereço MAC, Auth Key (se aplicável), agendamentos e controle individual.
4. **Integrações & Clima:** Área de configuração das integrações via API com campos seguros de chaves secretas, latitude/longitude, TTL do cache em memória e monitor de saúde do banco de dados RAM.

---
*Projeto idealizado como hub pessoal em IoT para automação diária.*
