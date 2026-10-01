# Arquitetura e Contexto do Backend

## 🧠 Core Backend Features

O Backend é o cérebro que comanda a operação de hardware e roteamento de requisições web. É escrito em Python 3.11 sob o framework FastAPI devido a sua performance e excelente suporte a I/O Assíncrono (`async`/`await`), que é absolutamente fundamental para conversar com periféricos de hardware via Bluetooth sem travar a interface da web.

### Estrutura de Arquivos

- `app/main.py`: Ponto de montagem da aplicação FastAPI, configuração do middleware de CORS (essencial para que o painel web possa chamar a API), roteamento principal e injeção do gerenciador de rotinas (APScheduler) no startup da aplicação.
- `app/api/routes.py`: Engloba todos os endpoints REST (`GET`, `POST`, `DELETE`). Interage como o "Controller" do MVC. Aqui recebemos as ações da web como `/sync`, `/weather/current`, `/devices`, efetuamos lógicas rasas e passamos o peso real para os módulos dentro de `services/`.
- `app/services/miband.py`: Classe robusta de integração que instancia as chamadas de nível de sistema (usando `bleak`) para se conectar ao MAC address da Mi Band, autenticar usando um Auth Key criptografado (se configurado) e interagir com as UUIDs (Characteristics) dos serviços do Bluetooth.
- `app/services/weather.py`: Módulo responsável pela abstração do protocolo de fetching climático com suporte a clima atual e previsão estendida (forecast). Tem suporte nativo ao Redis em RAM para manter a cota de uso segura e não desgastar o SD card.
- `app/core/scheduler.py`: Gerenciador central do **APScheduler**. Contém a rotina horária (`check_hourly_sync`) que calcula o intervalo decorrido comparando com `last_sync_time`, bem como o registro dinâmico de cron jobs para horários fixos configurados na Grid de agendamentos.
- `app/core/config.py`: Gestão limpa de ambiente usando `pydantic.BaseModel`. Lê variáveis vindas do container (`.env`) ou usa fallbacks espertos para testes em modo dev local.
- `app/core/cache.py`: Wrapper para a biblioteca do Redis em Python (`redis-py`). Construído para agir como um Singleton e não falhar na ausência do Redis, criando um simples cache de dicionário (`fallback`) caso o serviço caia, garantindo alta disponibilidade.

### 🔄 Concorrência, Agendamentos e Bluetooth

Interagir com Bluetooth requer concorrência e tratamentos explícitos de Timeout, pois o sinal se perde facilmente ou a pulseira pode estar dormindo (Sleep Mode).
- O fluxo de agendamento automático é estrito: **1º Busca Clima Estendido -> 2º Envia Clima para a pulseira -> 3º Conecta via BLE e extrai passos/bateria -> 4º Atualiza `last_sync_time` e métricas no Redis e SQLite**.
- Todo processo da biblioteca Bleak usa sintaxes assíncronas estritas.
- O container do backend é forçosamente rodado em `network_mode: "host"` pois o Docker em bridge mode não tem privilégios para conversar com as placas de antena interna do Raspberry Pi.
- Permissões estendidas mapeiam o volume local `/var/run/dbus` para que o Python saiba falar com o OS linux base.
