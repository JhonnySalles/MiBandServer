# Visão Geral Completa da Arquitetura - MiBand 6 Server

## 🏗️ Padrão e Tecnologias

O projeto **MiBand 6 Server** foi desenhado como um hub IoT autônomo, otimizado para rodar de forma eficiente e segura em um **Raspberry Pi 4**. A aplicação é dividida em serviços isolados operados via **Docker**, orquestrados pelo `docker-compose.yml`.

- **Orquestração e Deploy:** O sistema roda em Docker (3 containers principais: Backend, Frontend, Redis). O container do backend tem permissões elevadas (`network_mode: "host"`, `privileged: true` e acesso a `/var/run/dbus`) para acessar o hardware Bluetooth diretamente.
- **Backend (Core IoT):** Construído com **Python 3.11** utilizando **FastAPI**. Responsável pela comunicação assíncrona com dispositivos BLE utilizando a biblioteca **Bleak**. Também conta com o **APScheduler** para gerenciar as rotinas automáticas em background (cron jobs) das requisições de sincronização.
- **Banco de Dados (Relacional):** Utiliza o **SQLite** para persistência no disco via volumes do Docker, o que facilita o manuseio e backup sem sobrecarregar os recursos da máquina. A camada de modelo e query é feita através do **SQLModel** (wrapper do SQLAlchemy / Pydantic).
- **Banco de Dados (In-Memory / Cache):** Serviço do **Redis** para abrigar dados transitórios, retornos de APIs (clima) e últimas métricas processadas, visando proteger a vida útil do cartão SD contra excesso de escritas sequenciais.
- **Frontend (Painel de Gerenciamento):** Uma SPA (Single Page Application) minimalista porém premium. Construída puramente com **Vite**, **TypeScript**, **Vanilla CSS** e gráficos do **Chart.js**. Desenhada com temática _Glassmorphism_ e paleta _Dark Mode_ para uma UX aprimorada e moderna.

## 📂 Estrutura Macro do Projeto

- `backend/`: Código fonte da API em Python.
  - `alembic/`: Diretórios base para os arquivos de migrações estruturais do banco (schema updates).
  - `app/api/`: Rotas (`/api/sync`, `/api/config`, `/api/devices`, `/api/integrations`, `/api/weather`, etc).
  - `app/core/`: Camada de configuração e setup (`config.py`, `database.py`, `cache.py`).
  - `app/services/`: Camada inteligente que processa as regras de negócio (`miband.py` para comunicação de hardware, `weather.py` para integração REST com serviços meteorológicos).
- `frontend/`: Aplicação web para consumo do backend.
  - `src/`: Lógica central (TS e CSS). O index fica na raiz (`index.html`).
- `docs/ia_context/`: Central de conhecimento arquitetural dedicada a IA assistentes contendo recortes e especificações técnicas sobre a regra de negócio.

## 🤝 Fluxo de Comunicação e Assincronismo

Toda a interação com o hardware físico (pulseira Xiaomi) obedece um rigoroso processo de timeout e fallback implementado no `miband_service`. Por ser uma rádio BLE, que é propensa a flutuações e interferências, requisições de pareamento, escrita (`auth_key`) e notificação de eventos são envelopadas assincronamente e mantêm seus estados registrados com logs de progresso (`SyncHistory`). Quando a pulseira responde, os dados resultantes são tratados na camada `services` e repassados em cascata tanto para o persistente (SQLite) quanto para a visualização instantânea (Redis RAM).

## 🚀 Proteção de Hardware e Performance

Um dos grandes destaques do projeto é ter levado em consideração as limitações de um Single Board Computer (Raspberry Pi rodando em cartão SD):
- Implementação de um `CacheService` com fallback inteligente em memória Python.
- Redis despido de opções de salvamento (`--save "" --appendonly no`), atuando estritamente como RAM para o rápido consumo do dashboard Web e bloqueio de requisições excessivas.
- Logs e rastros não críticos são limitados na persistência e guardados majoritariamente no DB in-memory.
