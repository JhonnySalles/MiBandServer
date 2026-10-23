# Documentação Técnica — MiBand 6 Server

Bem-vindo à central de documentação técnica do **MiBand 6 Server**, um hub IoT autônomo e de alta performance projetado para rodar em Raspberry Pi 4 e integrar pulseiras **Xiaomi Mi Smart Band 6** via Bluetooth Low Energy (BLE).

---

## 📚 Índice de Documentos

### 1. Protocolo e Sincronização do Dispositivo
* **[Especificação Completa do Protocolo Mi Smart Band 6](file:///d:/Projetos/MiBandServer/docs/miband6_protocol_specification.md)**  
  Manual técnico aprofundado contendo o mapeamento completo de serviços GATT, handshake criptográfico ECDH B-163, enquadramento de chunks Huami 2021, empacotamento de previsão do tempo em 6 pacotes, gravação/leitura de 10 slots de alarmes, lembretes de eventos, relógio mundial, configurações de hardware (pulso, lift wrist, modo noturno, DND, idioma) e métricas avançadas (PAI, Estresse HRV, Oxímetro SpO2, Metas de Passos e Calorias).

### 2. Arquitetura do Sistema
* **[Visão Geral da Arquitetura Completa](file:///d:/Projetos/MiBandServer/docs/ia_context/architecture_complete.md)**  
  Apresentação holística da solução: orquestração em Docker, comunicação assíncrona BLE com proteção contra desgaste de cartão SD, fallback de cache em memória RAM e divisão em microsserviços.

* **[Arquitetura do Backend](file:///d:/Projetos/MiBandServer/docs/ia_context/backend/backend_architecture.md)**  
  Detalhamento dos componentes em Python 3.11 / FastAPI: gerenciador de rotinas em background (**APScheduler**), camada de protocolo BLE (**Bleak**), módulo isolado de testes com streaming Server-Sent Events (**SSE**), serviços de clima e controle de concorrência com travas assíncronas.

* **[Arquitetura de Banco de Dados e Cache](file:///d:/Projetos/MiBandServer/docs/ia_context/db/database_architecture.md)**  
  Modelagem de entidades relacionais em **SQLite** com **SQLModel**, auto-migrações em runtime, histórico intradiário e camada de alta velocidade em **Redis** para proteção do hardware.

* **[Arquitetura do Frontend](file:///d:/Projetos/MiBandServer/docs/ia_context/frontend/frontend_architecture.md)**  
  Especificação da Single Page Application (SPA) construída com **Vite**, **TypeScript** e **Vanilla CSS** (estilo Glassmorphism / Dark Mode), detalhando as abas de Dashboard, Histórico, Dispositivos, Clima, Configurações da Pulseira e Laboratório de Testes em tempo real.

---

## 🛠️ Resumo Rápido da Arquitetura

```
+------------------------------------------------------------------------------------+
|                                    Navegador Web                                   |
|       SPA em Vite + TypeScript: Dashboard | Configurações | Testes SSE | Clima     |
+------------------------------------------------------------------------------------+
                                         │ (HTTP REST / SSE Event-Stream)
                                         ▼
+------------------------------------------------------------------------------------+
|                           Backend FastAPI (Python 3.11)                            |
|  - Scheduler (APScheduler): Sincronizações automáticas periódicas                  |
|  - Protocol Engine (Bleak): Handshake ECDH B-163, Cifra AES-128, Chunks Huami 2021 |
|  - Test Runner: Execuções isoladas BLE com logs e progresso via Server-Sent Events |
+------------------------------------------------------------------------------------+
                    │                                             │
      (Leitura/Escrita Relacional)                     (Cache RAM Transitório)
                    ▼                                             ▼
+---------------------------------------+     +--------------------------------------+
|       Banco Persistente (SQLite)      |     |           Cache Redis em RAM         |
|  DeviceConfig, BandSettings, Logs     |     |  Métricas em tempo real, Clima, TTL  |
+---------------------------------------+     +--------------------------------------+
                    │
                    ▼ (BLE 5.0 Radio)
+------------------------------------------------------------------------------------+
|                       Xiaomi Mi Smart Band 6 (Hardware Real)                       |
|  Passos, Frequência Cardíaca, Oxímetro SpO2, Estresse HRV, PAI, Clima, Alarmes...  |
+------------------------------------------------------------------------------------+
```
