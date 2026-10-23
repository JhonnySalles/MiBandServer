# Visão Geral Completa da Arquitetura — MiBand 6 Server

## 🏗️ Padrão e Tecnologias

O projeto **MiBand 6 Server** foi desenhado como um hub IoT autônomo e de alta confiabilidade, otimizado para operar ininterruptamente em um **Raspberry Pi 4** (ou qualquer ambiente Linux/Windows com adaptador BLE 5.0). A aplicação é dividida em serviços isolados operados via **Docker**, orquestrados pelo `docker-compose.yml`.

- **Orquestração e Deploy:** O sistema roda em Docker (3 containers principais: Backend, Frontend e Redis). O container do backend opera com `network_mode: "host"`, `privileged: true` e montagem do socket do sistema operacional (`/var/run/dbus`) para acessar o hardware Bluetooth diretamente com baixa latência.
- **Backend (Core IoT):** Construído com **Python 3.11** utilizando **FastAPI**. Responsável pela comunicação assíncrona com dispositivos BLE utilizando a biblioteca **Bleak**, criptografia elíptica ECDH B-163 e AES-128-ECB. Conta com o **APScheduler** para gerenciar as rotinas automáticas em background (cron jobs e intervalos periódicos) e um motor de testes isolados com streaming via **Server-Sent Events (SSE)**.
- **Banco de Dados (Relacional):** Utiliza o **SQLite** para persistência no disco via volumes do Docker, garantindo portabilidade com zero sobrecarga de memória RAM. A camada de modelo e query é feita através do **SQLModel** (wrapper do SQLAlchemy / Pydantic) com auto-migrações seguras em tempo de execução.
- **Banco de Dados (In-Memory / Cache):** Serviço do **Redis** configurado sem escrita em disco (`--save "" --appendonly no`) para abrigar dados transitórios, retornos meteorológicos de APIs externas e últimas métricas instantâneas, protegendo a vida útil do cartão micro-SD do Raspberry Pi contra desgaste.
- **Frontend (Painel SPA):** Interface Web moderna construída com **Vite**, **TypeScript**, **Vanilla CSS** e gráficos do **Chart.js**. Desenhada com estética premium *Glassmorphism*, paleta *Dark Mode* (`#0f172a`), tipografia moderna (*Outfit*) e feedback visual imediato em tempo real.

---

## 📂 Estrutura Macro do Projeto

- `backend/`: Código fonte da API em Python.
  - `app/api/`: Rotas REST e SSE:
    - `routes.py`: Endpoints de dispositivos, métricas históricas, sincronização manual e integrações.
    - `band_settings_routes.py`: Endpoints de leitura, persistência e sincronização de configurações de hardware (alarmes, relógio mundial, lembretes, gestos, modo noturno, idioma, estresse, metas).
    - `test_routes.py`: Endpoints do Laboratório de Testes (`/api/test/stream` com SSE e prévias climáticas).
  - `app/core/`: Camada de configuração e setup (`config.py`, `database.py`, `cache.py`, `scheduler.py`).
  - `app/services/`: Camada de regras de negócio e hardware:
    - `miband_protocol.py`: Implementação completa do protocolo Huami 2021 (Handshake ECDH B-163, enquadramento de chunks, previsão do tempo em 6 pacotes, alarmes, relógio mundial, SpO2, estresse, PAI, metas).
    - `miband.py`: Orquestrador de sincronização em produção com concorrência protegida por `asyncio.Lock()`.
    - `miband_test.py`: Executor de testes diagnósticos pontuais em modo isolado (não grava no histórico de produção).
    - `weather.py`: Integração com provedores meteorológicos (Open-Meteo, OpenWeatherMap, WeatherAPI) com conversão de ícones Huami.
- `frontend/`: Aplicação web Single Page Application.
  - `index.html`: Layout mestre dividido em 6 abas dinâmicas.
  - `src/main.ts`: Inicialização, roteamento de abas, consumo de métricas e gráficos Chart.js.
  - `src/band-settings-tab.ts`: Gerenciamento completo de configurações da pulseira (alarmes, metas, estresse, lembretes, idioma).
  - `src/test-tab.ts`: Gerenciador do Laboratório de Testes com cliente SSE, console de logs coloridos e feedback visual.
  - `src/custom-select.ts`: Componente visual de comboboxes modernos e acessíveis.
  - `src/style.css`: Design system sob medida em CSS3 com glassmorphism.
- `docs/`: Documentação técnica completa e especificações de engenharia reversa.

---

## 🤝 Fluxo de Comunicação e Concorrência Bluetooth

Interações via rádio BLE estão sujeitas a flutuações de alcance, interferências eletromagnéticas e sono profundo da pulseira (Sleep Mode). Por isso, o sistema implementa:

1. **Trava de Concorrência (`_ble_lock`):**  
   Um `asyncio.Lock()` global assegura que rotinas automáticas de sincronização, chamadas de teste manual e requisições de configuração nunca colidam na mesma controladora Bluetooth. Caso o canal esteja ocupado, a API retorna `HTTP 409 Conflict` imediatamente com mensagem amigável.
2. **Separação Estrita de Ambientes (Produção vs Teste):**  
   - O **Modo Produção** (`sync_band`) extrai telemetria, atualiza o cache Redis, persiste no banco SQLite e atualiza o `last_sync_time`.
   - O **Laboratório de Testes** (`miband_test_service`) opera de forma 100% isolada, emitindo eventos de progresso e logs via Server-Sent Events diretamente para o console web, sem poluir os gráficos e históricos do usuário.
3. **Pipeline de Sincronização Automatizada:**  
   Quando o agendador dispara um ciclo:
   1. Coleta a previsão do tempo externa mais recente (com cache em RAM).
   2. Conecta ao dispositivo BLE e executa autenticação ECDH B-163.
   3. Sincroniza o relógio interno com fuso horário em quartos de hora (`0x2A2B`).
   4. Transmite a suíte de clima em 6 pacotes criptografados.
   5. Transmite metas de atividade (passos e calorias), escore PAI e configuração de estresse.
   6. Extrai passos, distância, calorias e bateria.
   7. Grava métricas no banco de dados e atualiza o dashboard.
