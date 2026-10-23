# Arquitetura e Contexto do Backend — MiBand 6 Server

## 🧠 Core Backend Features

O Backend é o motor de execução que comanda o hardware Bluetooth, processa algoritmos biométricos e expõe a API HTTP/SSE para o painel web. É escrito em **Python 3.11** sobre o framework **FastAPI**, tirando proveito máximo do modelo assíncrono (`async`/`await`) com a biblioteca **Bleak**.

---

### Estrutura de Módulos e Responsabilidades

#### 1. Camada de Aplicação e Roteamento (`app/api/`)
* **`app/main.py`**: Ponto de montagem da aplicação FastAPI, configuração de middlewares de CORS, inicialização do sistema de logs com retenção automática, e injeção do gerenciador de rotinas (**APScheduler**) no startup da aplicação.
* **`app/api/routes.py`**: Endpoints de gerenciamento geral de dispositivos (`/api/devices`), histórico de sincronizações (`/api/sync/history`), consulta de métricas mais recentes (`/api/metrics/latest`), busca de previsões climáticas e varredura BLE local (`/api/devices/scan`).
* **`app/api/band_settings_routes.py`**: Controla as configurações de hardware da Mi Smart Band 6:
  * `GET /api/band/settings`: Retorna a configuração gravada para a pulseira (alarmes, lembretes, relógio mundial, levantamento de pulso, modo noturno, idioma, estresse, metas).
  * `PUT /api/band/settings`: Atualiza as configurações no banco SQLite.
  * `POST /api/band/settings/sync`: Transmite configurações selecionadas (ou todas via `scope: "all"`) diretamente para o hardware da pulseira via BLE.
  * `POST /api/band/settings/read`: Consulta os slots de alarme configurados na pulseira e sincroniza no banco de dados.
* **`app/api/test_routes.py`**: Motor do Laboratório de Testes em tempo real:
  * `POST /api/test/stream`: Endpoint reativo baseado em **Server-Sent Events (SSE)** via `StreamingResponse`. Permite disparar diagnósticos isolados (passos, bateria, relógio, alarme, frequência cardíaca, oximetria SpO2, estresse, metas de atividade, PAI, clima, notificações, vibração) recebendo logs e percentual de progresso em tempo real.
  * `GET /api/test/weather/preview`: Obtém a prévia meteorológica estendida para visualização e edição nos cards de teste.

#### 2. Camada de Protocolo e Negócio (`app/services/`)
* **`app/services/miband_protocol.py`**: A espinha dorsal da integração BLE da Mi Smart Band 6:
  * Handshake ECDH Curva B-163 e derivação de chave de sessão AES-128-ECB.
  * Enquadramento de pacotes em chunks de tamanho variável respeitando a MTU.
  * `sync_time()`: Empacotamento de data/hora em 10 bytes com fuso em quartos de hora (`0x2A2B`).
  * `send_weather_chunked()`: Transmissão da suíte completa de previsão do tempo em 6 pacotes no endpoint `0x0090`.
  * `set_alarms()` e `request_alarms()`: Gravação e leitura dos 10 slots nativos de alarmes com suporte a repetição, soneca e limpeza de slots vazios.
  * `set_fitness_goals()`: Envio de metas diárias de passos e calorias (`0x06, 0x01, 0x00, step_l, step_h, cal_l, cal_h`).
  * `send_pai_score()`: Transmissão da pontuação PAI acumulada e do dia (`0x01, 0x18, total_l, total_h, today_l, today_h`).
  * `set_stress_monitoring()`: Configuração de monitoramento de estresse em repouso (`0x06, 0x12, en, int`).
  * `measure_spo2()`: Disparo e leitura do sensor óptico de oximetria em `0x2A39` / `0x2A37`.
  * `measure_stress()`: Leitura de variabilidade cardíaca (HRV) e cálculo do índice de estresse de 1 a 100.
  * `trigger_vibrate()` e `stop_vibrate()`: Disparo e interrupção controlada de vibração háptica.
  * `send_notification()`: Envio de pop-up New Alert no display com sanitização UTF-8.
* **`app/services/miband.py`**: Orquestrador de sincronização em ambiente de produção com proteção contra concorrência via `_ble_lock`.
* **`app/services/miband_test.py`**: Executor de testes diagnósticos que utiliza gerador de filas `asyncio.Queue` para emitir eventos de progresso e logs detalhados sem persistir dados no histórico do usuário.
* **`app/services/weather.py`**: Serviço meteorológico com suporte a múltiplos provedores externos (Open-Meteo, OpenWeatherMap, WeatherAPI) e cache em RAM no Redis.

#### 3. Camada de Agendamento e Concorrência (`app/core/`)
* **`app/core/scheduler.py`**: Gerenciador do **APScheduler**. Executa verificações periódicas automáticas de sincronização, recupera credenciais do banco SQLite, coleta o clima e transmite telemetria e configurações para a pulseira.
* **`app/core/cache.py`**: Wrapper para o Redis com mecanismo de fallback transparente para dicionário em memória Python, garantindo que o servidor permaneça operacional mesmo se o Redis estiver indisponível.
* **`app/core/database.py`**: Definição dos modelos SQLModel e auto-migração estrutural.
