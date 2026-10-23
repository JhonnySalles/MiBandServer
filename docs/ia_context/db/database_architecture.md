# Arquitetura de Banco de Dados, Migrations e Cache — MiBand 6 Server

## 🗄️ Persistência de Dados e Proteção de Hardware

A modelagem de dados do **MiBand 6 Server** foi projetada para equilibrar a persistência histórica de longo prazo com a proteção contra desgaste de gravação no cartão micro-SD do **Raspberry Pi 4**.

---

### 1. Armazenamento Relacional (SQLite + SQLModel)

O **SQLite** foi a escolha ideal por dispensar daemons pesados em segundo plano, manter consumo de memória RAM praticamente nulo e viabilizar backups instantâneos mediante cópia do arquivo `miband.db`. O **SQLModel** combina o mapeamento relacional do SQLAlchemy com a validação rigorosa de tipos do Pydantic.

#### Entidades do Sistema:

1. **`DeviceConfig`**:
   * Armazena os dispositivos pareados.
   * Campos: `id`, `mac_address` (chave única), `device_name`, `auth_key` (chave hexadecimal de 32 caracteres para autenticação ECDH), `sync_interval_hours`, `sync_intervals` (grade de horários como `"08:00,12:00,18:00,22:00"`), `auto_weather`, `is_active`, `last_sync_time`.
2. **`BandSettings`**:
   * Mantém as configurações específicas de hardware da Mi Smart Band 6.
   * Campos:
     * `device_mac`: Endereço MAC associado.
     * `event_reminders`: JSON com array de lembretes (título, data/hora).
     * `alarms`: JSON com array dos 10 slots de alarme (hora, minuto, ativado, soneca, máscara de dias).
     * `world_clocks`: JSON com array de cidades e fusos horários.
     * `lift_wrist_mode`, `lift_wrist_start`, `lift_wrist_end`, `lift_wrist_speed`: Controle de acendimento da tela ao girar o pulso.
     * `night_mode`, `night_mode_start`, `night_mode_end`: Controle de redução de brilho noturno.
     * `dnd_mode`: Modo Não Perturbe (Desligado, Sempre, Inteligente/Sono, Agendado).
     * `wear_location`: Pulso esquerdo (`"left"`) ou direito (`"right"`).
     * `language`: Código ISO de idioma do sistema (`"pt_BR"`, `"en_US"`, etc.).
     * `heart_rate_interval`: Frequência de monitoramento cardíaco contínuo (1, 5, 10, 30 min).
     * `step_goal`: Meta diária de passos (ex: 8.000).
     * `calorie_goal`: Meta diária de calorias queimadas em kcal (ex: 300).
     * `all_day_stress`: Monitoramento contínuo de estresse automático (booleano).
     * `stress_interval`: Frequência da amostragem de estresse em minutos.
3. **`ActivityLog`**:
   * Registros consolidados de telemetria coletados a cada ciclo de sincronização.
   * Campos: `device_mac`, `timestamp`, `steps`, `distance_meters`, `calories`, `heart_rate`, `battery_level`, `spo2` (oximetria), `stress` (nível 1-100), `pai_today` (pontuação do dia), `pai_total` (pontuação semanal acumulada).
4. **`IntradayActivitySample`**:
   * Séries temporais minuto a minuto para plotagem de gráficos intradiários detalhados.
   * Campos: `device_mac`, `timestamp`, `steps`, `heart_rate`, `raw_category`, `spo2`, `stress`.
5. **`SyncHistory`**:
   * Auditoria de execuções de sincronização (status, duração, mensagens e erros técnicos detalhados).
6. **`IntegrationConfig`**:
   * Configuração de provedores meteorológicos (Open-Meteo, OpenWeatherMap, WeatherAPI), tokens de acesso, geolocalização (latitude, longitude, cidade) e tempo de vida do cache (TTL).

---

### 2. Mecanismo de Migrações em Runtime

Para evitar problemas de incompatibilidade de versão quando o banco de dados pré-existente no Raspberry Pi recebe novas colunas, o arquivo `backend/app/core/database.py` conta com um mecanismo automático de auto-migração executado no startup (`init_db`):
* Executa `PRAGMA table_info(nome_tabela)` para inspecionar dinamicamente o esquema da tabela SQLite.
* Compara as colunas físicas com o modelo SQLModel.
* Dispara comandos `ALTER TABLE ... ADD COLUMN` automaticamente para qualquer campo novo (como `step_goal`, `calorie_goal`, `all_day_stress`, `stress_interval`, `spo2`, `stress`, `pai_today`, `pai_total`).

---

### 3. Camada de Cache em RAM (Redis)

O serviço do Redis roda acoplado no `docker-compose.yml` sem persistência em disco (`--save "" --appendonly no`):
* **Proteção do Cartão SD:** Consultas frequentes do dashboard web (`/api/metrics/latest`, prévias climáticas, status de conexão) são servidas diretamente da memória RAM.
* **Namespaces Estruturados:**
  * `weather:current:<lat>:<lon>` (TTL de 30 minutos).
  * `weather:forecast:<lat>:<lon>` (TTL de 60 a 120 minutos).
  * `metrics:latest:<mac>` (Atualizado instantaneamente a cada sincronização).
* **Fallback Inteligente:** Caso o container do Redis seja interrompido, a classe `CacheService` faz fallback automático para um dicionário volátil em memória Python, mantendo o sistema 100% operacional sem lançar exceções para os clientes.
