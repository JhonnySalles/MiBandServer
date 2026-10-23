# MiBand 6 Server — Hub IoT para Raspberry Pi 4

O **MiBand 6 Server** é um hub IoT autônomo e de alta performance orquestrado em Docker, desenvolvido para conectar, sincronizar, monitorar e configurar pulseiras **Xiaomi Mi Smart Band 6** via Bluetooth Low Energy (BLE). Foi especialmente otimizado para rodar de forma contínua em um **Raspberry Pi 4**, protegendo o cartão micro-SD contra desgaste e operando de forma 100% local e independente de nuvens de terceiros.

---

## 🌟 Principais Funcionalidades

### 1. Sincronização Biométrica e de Atividade
- **Telemetria Diária:** Leitura instantânea de passos totais, distância percorrida em metros, calorias gastas e percentual de bateria.
- **Oxímetro de Pulso (SpO2):** Acionamento do sensor infravermelho para medição de saturação de oxigênio no sangue.
- **Monitoramento de Estresse (HRV):** Aferição de variabilidade da frequência cardíaca e cálculo do índice de estresse de 1 a 100 com classificação oficial (Relaxado, Leve, Moderado, Alto).
- **Pontuação PAI (Personal Activity Intelligence):** Sincronização do algoritmo de pontuação aeróbica semanal e diária diretamente no display da pulseira.
- **Metas de Atividade Física:** Configuração de metas personalizadas de passos e calorias com barras de progresso visuais e comemoração na pulseira.
- **Frequência Cardíaca:** Monitoramento sob demanda e configuração do ciclo de medições periódicas contínuas (1, 5, 10 ou 30 minutos).

### 2. Suíte Meteorológica Huami 2021
- **Previsão do Tempo Completa em 6 Pacotes:** Envio de localização (cidade), clima atual, índice de qualidade do ar (AQI), previsão estendida de 7 dias com temperaturas mínimas e máximas, velocidade do vento, umidade relativa e horários de nascer e pôr do sol.
- **Múltiplos Provedores:** Suporte integrado a **Open-Meteo** (gratuito e sem necessidade de token), **OpenWeatherMap** e **WeatherAPI**.
- **Geolocalização:** Busca de cidades e detecção automática de latitude/longitude pelo navegador.

### 3. Central de Configurações da Pulseira
- **Alarmes Nativos (10 Slots):** Configuração com seleção individual de dias da semana, disparo único, soneca e limpeza automática de slots fantasmas.
- **Lembretes de Eventos:** Até 15 compromissos com exibição de título e vibração na data e hora marcadas.
- **Relógio Mundial:** Até 10 capitais ou fusos com relógio digital atualizado em tempo real.
- **Controle de Hardware e Sensores:**
  - Gesto de Levantar o Pulso (*Lift Wrist*) com ajuste de velocidade e horário programado.
  - Modo Noturno (*Night Mode*) com redução automática de brilho ao pôr do sol.
  - Não Perturbe (*DND Inteligente*) com silenciamento automático ao detectar o sono do usuário.
  - Localização de Uso (pulso esquerdo ou direito) para calibração do acelerômetro.
  - Idioma do display (Português, Inglês, Espanhol, Francês, Alemão, Italiano, Russo e Chinês).

### 4. Laboratório de Testes em Tempo Real
- **Streaming via Server-Sent Events (SSE):** Execução de testes e diagnósticos BLE isolados com feedback de progresso percentual e mensagens em tempo real.
- **Console Interativo:** Terminal embutido com logs coloridos por severidade (`INFO`, `WARN`, `ERROR`, `OK`) e cópia rápida para clipboard.
- **Simulador de Clima e Notificações:** Edição manual de previsão do tempo antes do envio e disparo de alertas de texto e vibração física (*Find Device*).

### 5. Arquitetura SBC & Proteção do Cartão SD
- **Cache em RAM (Redis):** Métricas instantâneas e requisições climáticas são mantidas na memória RAM do Raspberry Pi sem persistência desnecessária no disco, prolongando a vida útil do cartão SD.
- **Auto-Migrações:** O banco **SQLite** inspeciona e atualiza o esquema relacional automaticamente na inicialização sem perda de dados.

---

## 🛠️ Stack Tecnológica

* **Backend:** Python 3.11, FastAPI, Bleak (BLE assíncrono), APScheduler, SQLModel (SQLite) e Redis-py.
* **Frontend:** Vite, TypeScript, Vanilla CSS3 (Glassmorphism / Dark Mode) e Chart.js.
* **Infraestrutura:** Docker e Docker Compose (containers de Backend com `network_mode: "host"`, Frontend com Nginx Alpine e Redis em RAM).

---

## 🚀 Como Executar

### 1. Pré-requisitos
* **Raspberry Pi 4** (ou computador com Linux/Windows e adaptador Bluetooth BLE 5.0).
* **Docker** e **Docker Compose** instalados.

### 2. Configuração de Variáveis
Copie o arquivo de exemplo e configure as portas desejadas:

```bash
cp .env.example .env
```

```env
FRONTEND_PORT=8080
VITE_API_URL=http://localhost:8190
```

### 3. Inicialização via Docker
```bash
docker compose up --build -d
```

Acesse o painel web em seu navegador: `http://<ip-do-raspberry>:8080`.

---

## 📖 Documentação Completa

Para detalhes aprofundados sobre arquitetura e protocolos de comunicação, consulte a pasta [`docs/`](file:///d:/Projetos/MiBandServer/docs):

* **[Índice Geral de Documentação](file:///d:/Projetos/MiBandServer/docs/README.md)**
* **[Especificação Completa do Protocolo BLE da Mi Smart Band 6](file:///d:/Projetos/MiBandServer/docs/miband6_protocol_specification.md)**
* **[Visão Geral da Arquitetura Completa](file:///d:/Projetos/MiBandServer/docs/ia_context/architecture_complete.md)**
* **[Arquitetura do Backend](file:///d:/Projetos/MiBandServer/docs/ia_context/backend/backend_architecture.md)**
* **[Arquitetura de Banco de Dados e Cache](file:///d:/Projetos/MiBandServer/docs/ia_context/db/database_architecture.md)**
* **[Arquitetura do Frontend](file:///d:/Projetos/MiBandServer/docs/ia_context/frontend/frontend_architecture.md)**
* **[Relatório Técnico de Engenharia Reversa REA](file:///d:/Projetos/MiBandServer/documento.md)**

---

*Projeto desenvolvido para controle, automação e monitoramento autônomo da Mi Smart Band 6.*
