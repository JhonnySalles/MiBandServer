# Arquitetura de Banco de Dados e Migrations

## 🗄️ Persistência de Dados e Cache

A modelagem de dados do projeto é arquitetada sob a dicotomia de uso: **Armazenamento de Longo Prazo** vs **Dados Efêmeros de Alta Carga**.

### Armazenamento Persistente (SQLite + SQLModel)
O SQLite foi escolhido intencionalmente contra opções como PostgreSQL ou MySQL para minimizar uso de memória RAM num ambiente de SoC (Raspberry Pi) e manter os backups tão simples quanto copiar o arquivo `miband.db`.
O **SQLModel** brilha unindo as classes de declaração do banco diretamente com Pydantic, o que permite o FastAPI gerar schemas JSON nativos na validação das rotas com zero código boilerplate adicional.

Entidades:
1. `DeviceConfig`: Guarda múltiplas pulseiras pareadas com nome, Endereço MAC (chave vital para Bleak), Auth Key, se está ativo e sua respectiva grade de sincronização (ex: "08:00,12:00,20:00").
2. `IntegrationConfig`: Configurações atreladas à rede mundial. Guarda tokens de API meteorológicas (OpenWeatherMap, WeatherAPI) junto à localização (Latitude e Longitude).
3. `ActivityLog`: Logs pesados e analíticos. Umidade de passos, calorias, BPM, etc.
4. `SyncHistory`: Armazena seções de tentativas, gravando metadados quando há falhas para depuração posterior.

### Pipeline de Evolução (Alembic)
O banco conta com a infraestrutura de controle de versão (Migrations) do **Alembic**.
- O setup de migrations está hospedado no repositório `backend/alembic/`.
- O diretório `backend/alembic/versions` abriga os deltas (`.py` automáticos gerados com `alembic revision --autogenerate`).
- O script base foi atualizado no `env.py` injetando diretamente o `SQLModel.metadata`, ou seja, novas classes adicionadas ou alteradas no Python refinarão tabelas de banco sozinhas após os comandos do desenvolvedor.

### Abstração em Memória (Redis)
Como operações de gravação e leitura em cartão micro-SD no Raspberry causam danos nos blocos do circuito:
- Dados como `Última verificação de Clima` e `Métricas em Tempo Real na Dashboard` jamais rodam queries no `ActivityLog` do banco de disco a primeira vista. O backend busca prioritariamente essas requisições através do Redis.
- As chaves de namespace acompanham a regra: `weather:forecast:<provedor>:<lat>:<lon>` com tempo de vida fixo (TTL de 30 min a 2 horas).
