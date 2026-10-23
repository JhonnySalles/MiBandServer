# Especificação Completa do Protocolo e Sincronização — Xiaomi Mi Smart Band 6

Este documento estabelece a especificação técnica canônica e definitiva da comunicação Bluetooth Low Energy (BLE) da **Xiaomi Mi Smart Band 6** (codinome Huami *pumptkin* / modelo *XMSH15HM*), detalhando todos os serviços GATT, protocolos criptográficos, layouts de pacotes em bytes, rotinas de empacotamento, envio e recebimento de dados, bem como sua implementação de referência no **MiBandServer**.

---

## 1. Visão Geral do Hardware e Arquitetura BLE

A Xiaomi Mi Smart Band 6 opera com hardware de alta eficiência baseado no SoC Dialog Semiconductor DA14697 (ARM Cortex-M33) acompanhado de acelerômetro e giroscópio de 6 eixos, sensor óptico fotopletismográfico (PPG) com LEDs verde (frequência cardíaca) e infravermelho (oximetria SpO2), motor háptico de vibração e display AMOLED de 1.56" (152 x 486 pixels).

Diferente das gerações legadas (Mi Band 2, 3 e 4), que utilizavam comandos diretos via características GATT simples, a Mi Band 6 opera com a pilha **Huami 2021**:
* **Canais Emulados com Enquadramento de Chunks (Chunked Streams)**: Fluxo de dados particionado em pacotes de tamanho adaptável aos limites de MTU BLE (padrão 23 bytes, negociável até 512 bytes).
* **Handshake Criptográfico Baseado em Curva Elíptica (ECDH B-163)**: Troca de chaves públicas efêmeras de 24 bytes para derivação de segredo compartilhado.
* **Cifragem Simétrica de Mensagens (AES-128-ECB)**: Mensagens trafegadas no canal de controle são encriptadas com preenchimento com zeros (zero-padding) e chave de mensagem calculada via XOR do identificador do endpoint com a chave de sessão.

```
+-----------------------------------------------------------------------------------------+
|                          Camada de Aplicação Huami (Endpoints)                          |
|  [0x0082 Auth]   [0x0090 Compat / Clima / Alarmes / Configs]   [0x0004 / 5 Atividade]   |
+-----------------------------------------------------------------------------------------+
|                      Camada de Criptografia & Enquadramento Chunked                     |
|        Header (0x03) | Flags (Enc/ACK) | Handle | Counter | Payload AES-128-ECB         |
+-----------------------------------------------------------------------------------------+
|                            GATT (Generic Attribute Profile)                             |
|  00000016-... (Chunked Write)             |  00000017-... (Chunked Read / Notify)       |
|  00000007-... (Passos / Calorias)         |  0000180d-... (Heart Rate PPG / SpO2)       |
|  00001805-... (Current Time)              |  00001811-... (Alert Notification)          |
+-----------------------------------------------------------------------------------------+
|                            Bluetooth Low Energy (Camada Link)                           |
+-----------------------------------------------------------------------------------------+
```

---

## 2. Mapeamento de Serviços e Características GATT

| Serviço | UUID Base | Característica | Propriedades | Finalidade |
| :--- | :--- | :--- | :--- | :--- |
| **Huami Chunked 2021** | `0000fee0-0000-3512-2118-0009af100700` | `00000016-0000-3512-2118-0009af100700` | Write Without Response | Canal principal de escrita empacotada (Auth, Clima, Configurações, Alarmes) |
| **Huami Chunked Read** | `0000fee0-0000-3512-2118-0009af100700` | `00000017-0000-3512-2118-0009af100700` | Notify, Write | Canal de recebimento de dados empacotados e emissão de ACKs |
| **Huami Legacy Chunk** | `0000fee0-0000-3512-2118-0009af100700` | `00000020-0000-3512-2118-0009af100700` | Write | Canal secundário legado de clima e chamadas CallSpec |
| **Huami Basic / Steps**| `0000fee0-0000-1000-8000-00805f9b34fb` | `00000007-0000-3512-2118-0009af100700` | Read, Notify | Leitura instantânea de passos, distância e calorias acumuladas no dia |
| **Huami Battery Legacy**| `0000fee0-0000-1000-8000-00805f9b34fb`| `00000006-0000-3512-2118-0009af100700` | Read, Notify | Nível detalhado de carga, status e timestamp da última recarga completa |
| **Huami Alert / Events**| `0000fee0-0000-1000-8000-00805f9b34fb`| `00000003-0000-3512-2118-0009af100700` | Write, Notify | Disparo de vibração háptica e notificações de eventos de hardware |
| **Heart Rate Service** | `0000180d-0000-1000-8000-00805f9b34fb` | `00002a37-0000-1000-8000-00805f9b34fb` | Notify | Notificação de frequência cardíaca (BPM) e pacotes PPG |
| **Heart Rate Control** | `0000180d-0000-1000-8000-00805f9b34fb` | `00002a39-0000-1000-8000-00805f9b34fb` | Write | Controle do sensor óptico PPG (medição contínua, manual, SpO2) |
| **Current Time Service**| `00001805-0000-1000-8000-00805f9b34fb`| `00002a2b-0000-1000-8000-00805f9b34fb` | Read, Write | Leitura e ajuste do relógio interno e fuso horário |
| **Immediate Alert**    | `00001802-0000-1000-8000-00805f9b34fb` | `00002a06-0000-1000-8000-00805f9b34fb` | Write Without Response | Comando padrão BLE de alerta físico (Localizar Dispositivo) |
| **Alert Notification** | `00001811-0000-1000-8000-00805f9b34fb` | `00002a46-0000-1000-8000-00805f9b34fb` | Write | Transmissão de alertas, chamadas e notificações na tela AMOLED |
| **Alert Control Point**| `00001811-0000-1000-8000-00805f9b34fb` | `00002a44-0000-1000-8000-00805f9b34fb` | Write | Habilitação e controle de categorias de notificação |
| **Device Info (DIS)**  | `0000180a-0000-1000-8000-00805f9b34fb` | `00002a24` a `00002a28`                | Read | Modelo, Fabricante, Versão de Firmware, Hardware e Serial |

---

## 3. Protocolo Criptográfico e Autenticação (Handshake ECDH B-163)

A Mi Smart Band 6 exige a conclusão bem-sucedida do handshake criptográfico antes de liberar qualquer operação de escrita nas características Huami ou leitura de dados protegidos.

### 3.1 Chave de Autenticação (`auth_key`)
* É uma chave simétrica de **16 bytes (32 caracteres hexadecimais)** atribuída à pulseira durante o pareamento inicial oficial com a conta Xiaomi/Zepp.
* Exemplo: `9b4e5f2a1c0d3e8a7b6c5d4e3f2a1b0c`.

### 3.2 Diagrama de Sequência do Handshake
```
Host (Servidor / RPi)                                            Mi Smart Band 6
       |                                                                |
       |--- 1. Subscrição em 0x0017 (Chunked Read / Notify) ----------->|
       |                                                                |
       |--- 2. TX 0x0016 [Init Auth: 0x04, 0x02, 0x00, 0x02 + PubK] --->|
       |       (PubK = 24 bytes ECDH Curva B-163 gerada no Host)        |
       |                                                                |
       |<-- 3. RX 0x0017 [Band PubK (24 bytes) + Random Challenge (16B)]|
       |                                                                |
       |    * Host calcula Shared Secret via Curva B-163                |
       |    * Deriva Session Key (16 bytes) combinando Shared Secret    |
       |      com a Auth Key cadastrada                                 |
       |    * Cifra o Random Challenge recebido com AES-128-ECB         |
       |                                                                |
       |--- 4. TX 0x0016 [Resp Auth: 0x05 + Encrypted Challenge] ------>|
       |                                                                |
       |<-- 5. RX 0x0017 [Status: 0x10, 0x05, 0x01 (Sucesso)] ----------|
       |    (Sessão Autenticada com Sucesso — Criptografia Habilitada)   |
```

### 3.3 Cifragem das Mensagens de Dados
Após o handshake, as mensagens transmitidas em endpoints criptografados (como `0x0090`) são cifradas por pacote:
$$\text{msg\_key}[i] = \text{session\_key}[i] \oplus (\text{handle} \ \& \ \text{0xFF})$$
* **Algoritmo:** AES-128 no modo ECB (Electronic Codebook).
* **Alinhamento:** Preenchimento com zeros (`\x00`) até atingir tamanho múltiplo de 16 bytes.

---

## 4. Enquadramento e Protocolo de Chunks (Chunked Streams)

Todas as comunicações com os endpoints de aplicação trafegam na característica `00000016-...` através do encapsulamento em **chunks**:

### 4.1 Estrutura do Cabeçalho de Chunk (5 Bytes)
```
Byte 0: Tipo de Chunk (0x03 = Enquadramento padrão)
Byte 1: Flags de Controle
        Bit 0: Continuação de chunk anterior (1) ou Primeiro chunk (0)
        Bit 3: Criptografado com Session Key (1) ou Plano (0)
        Bit 4: Requer confirmação de recebimento ACK (1)
Byte 2: Endpoint / Handle ID (ex: 0x90 para Compatibilidade/Clima/Alarmes, 0x82 para Auth)
Byte 3: Contador Sequencial de Pacotes (incrementado a cada transmissão)
Byte 4: Tamanho total do payload fragmentado (ou restante)
```

O host envia pacotes respeitando a MTU negociada da conexão BLE (tipicamente fatias de até 20 a 180 bytes por envio físico).

---

## 5. Sincronização de Data, Hora e Fuso Horário

* **Característica GATT:** `00002a2b-0000-1000-8000-00805f9b34fb` (Current Time Service)
* **Tipo:** Write with Response
* **Formato:** Estrutura binária exata de 10 bytes (`<HBBBBBBBBb`):

```
Offset  Tipo     Nome                   Descrição
[0..1]  uint16LE Ano                    Ex: 2026 -> 0xEA, 0x07
[2]     uint8    Mês                    1 a 12
[3]     uint8    Dia do Mês             1 a 31
[4]     uint8    Hora                   0 a 23
[5]     uint8    Minuto                 0 a 59
[6]     uint8    Segundo                0 a 59
[7]     uint8    Dia da Semana          1 = Segunda-feira ... 7 = Domingo (Padrão ISO)
[8]     uint8    Fração de Segundo      Frações de 1/256 segundos (padrão: 0x00)
[9]     int8     Fuso Horário (Quartos) Offset UTC em quartos de hora (Ex: UTC-3 = -3 * 4 = -12 -> 0xF4)
```

> **Importância do Fuso Horário:**  
> A Mi Smart Band 6 descarta silenciosamente previsões de tempo se o timestamp unix dos pacotes meteorológicos não for estritamente coerente com o offset de fuso configurado no relógio interno.

---

## 6. Sincronização e Envio de Previsão do Tempo (Weather Sync)

* **Canal:** `00000016-...` (Huami Chunked Write)
* **Endpoint:** `0x0090` (144)
* **Prefixo de Cabeçalho:** `[0x00, 0x00, 0xC1, 0x00]`
* **Criptografia:** Obrigatória (`session_key`)

O envio meteorológico canônico compõe-se de **6 pacotes independentes**:

```
+---------------------------------------------------------------------------------------+
| ID 8: Localização (Nome da Cidade em UTF-8 terminado em \0)                           |
+---------------------------------------------------------------------------------------+
| ID 2: Clima Atual (Timestamp, Fuso, Código Ícone, Temperatura Atual, Condição)        |
+---------------------------------------------------------------------------------------+
| ID 4: Qualidade do Ar (Timestamp, Fuso, Índice AQI int16, Descrição do Ar)           |
+---------------------------------------------------------------------------------------+
| ID 1: Previsão Estendida (Hoje + até 6 dias subsequentes com mín/máx/condição)       |
+---------------------------------------------------------------------------------------+
| ID 64: Vento e Umidade (Timestamp, Fuso, Texto de Vento em km/h, Texto de Umidade %)  |
+---------------------------------------------------------------------------------------+
| ID 16: Nascer e Pôr do Sol (Timestamp, Fuso, Hora/Min Nascer, Hora/Min Pôr do Sol)    |
+---------------------------------------------------------------------------------------+
```

### 6.1 Detalhamento dos 6 Pacotes:

1. **Localização (ID `0x08`):**  
   `[0x08] + <Nome da Cidade em UTF-8> + [0x00]`
2. **Clima Atual (ID `0x02`):**  
   `[0x02, ts_l, ts_ml, ts_mh, ts_h, tz_quarters, icon_code, temp_celsius] + <Condição UTF-8> + [0x00]`
3. **Qualidade do Ar — AQI (ID `0x04`):**  
   `[0x04, ts_l, ts_ml, ts_mh, ts_h, tz_quarters, aqi_l, aqi_h] + <Descrição UTF-8> + [0x00]`
4. **Previsão de Múltiplos Dias (ID `0x01`):**  
   `[0x01, ts_l, ts_ml, ts_mh, ts_h, tz_quarters, num_dias]` seguido por cada dia (iniciando obrigatoriamente por Hoje):  
   `[code_dia, code_noite, max_temp, min_temp] + <Texto Condição UTF-8> + [0x00]`
5. **Vento e Umidade (ID `0x40` / 64):**  
   `[0x40, ts_l, ts_ml, ts_mh, ts_h, tz_quarters] + <Vento UTF-8> + [0x00] + <Umidade UTF-8> + [0x00]`
6. **Nascer e Pôr do Sol (ID `0x10` / 16):**  
   `[0x10, ts_l, ts_ml, ts_mh, ts_h, tz_quarters, hora_nascer, min_nascer, hora_por, min_por]`

### 6.2 Tabela de Códigos Meteorológicos Huami:
| Código | Condição | Código | Condição | Código | Condição |
| :---: | :--- | :---: | :--- | :---: | :--- |
| `0` | Céu Limpo / Ensolarado | `7` | Chuva Leve | `17`| Nevasca / Frio Extremo |
| `1` | Parcialmente Nublado | `8` | Chuva Moderada | `18`| Névoa / Neblina |
| `2` | Nublado / Encoberto | `9` | Chuva Forte / Torrencial | `19`| Garoa / Chuvisco |
| `3` | Chuva com Vento | `10`| Chuva com Granizo | `20`| Tempestade de Areia |
| `4` | Tempestades / Trovoadas | `14`| Neve Leve | `21`| Poeira em Suspensão |
| `5` | Granizo | `15`| Neve Moderada | `22`| Chuva Forte Noturna |
| `6` | Chuva e Neve Mistas | `16`| Neve Forte | `25`| Ventania Severa |

---

## 7. Configuração e Leitura de Alarmes

A Mi Smart Band 6 possui **10 slots de memória independentes para alarmes** (slots de índice `0` a `9`).

### 7.1 Gravação de Alarmes (Host -> Pulseira)
* **Endpoint:** `0x0090` (144)
* **Estrutura de Comando:** 6 bytes por alarme
```
[0x01, 0x02, state_byte, hour, minute, repetition_mask]
```

#### Detalhamento do `state_byte`:
* **Bit 7 (0x80):** Alarme Habilitado (`1` = Ligado, `0` = Desligado).
* **Bit 6 (0x40):** Modo Soneca Desativado (`1` = Sem soneca / Não repetir, `0` = Soneca ativa a cada 10 min).
* **Bits 0..3 (0x0F):** Slot do Alarme (`0` a `9`).

#### Detalhamento da `repetition_mask`:
* `0x01`: Segunda-feira
* `0x02`: Terça-feira
* `0x04`: Quarta-feira
* `0x08`: Quinta-feira
* `0x10`: Sexta-feira
* `0x20`: Sábado
* `0x40`: Domingo
* `0x80`: Disparo Único (Sem repetição semanal)

> **Limpeza de Slots Fantasmas:**  
> Caso o usuário configure apenas 2 alarmes, os 8 slots remanescentes devem ser desativados explicitamente enviando:  
> `[0x01, 0x02, slot_index & 0x0F, 0x00, 0x00, 0x00]`. Isso impede que alarmes antigos continuem vibrando na pulseira.

### 7.2 Leitura de Alarmes da Pulseira (Pulseira -> Host)
1. O Host ativa subscrição de Notificações no canal `00000017-...`.
2. O Host transmite no endpoint `0x0090`:
   * Solicitação de Inventário: `[0x01, 0x0D]`
   * Solicitação Detalhada com Horários: `[0x01, 0xFF, 0x01, 0x00, 0x00, 0x00]`
3. A resposta da pulseira é descriptografada com `AES-128-ECB`.
4. O parser identifica os registros de 4 bytes por alarme:
   * **Byte 0:** Estado (Bit 7: ativado, Bit 6: soneca_off, Bits 0..3: índice).
   * **Byte 1:** Hora (0 a 23).
   * **Byte 2:** Minuto (0 a 59).
   * **Byte 3:** Máscara de Repetição.

---

## 8. Lembretes de Eventos e Relógio Mundial

### 8.1 Lembretes de Eventos (Event Reminders)
* **Endpoint:** `0x0090` (144)
* **Capacidade:** Até 15 eventos simultâneos na memória da pulseira.
* **Payload:**
  `[0x01, 0x01, index, year_low, year_high, month, day, hour, minute, repetition, text_len] + <Título UTF-8>`
* A pulseira acende a tela na data/hora programada exibindo o texto acompanhado de vibração.

### 8.2 Relógio Mundial (World Clocks)
* **Endpoint:** `0x0090` (144)
* **Capacidade:** Até 10 cidades mundiais exibidas no widget do relógio.
* **Payload:**
  `[0x01, 0x11, count] + [city_len, <Nome Cidade UTF-8>, tz_offset_min_low, tz_offset_min_high] x N`

---

## 9. Configurações de Usabilidade e Hardware

Todas as configurações operam no Endpoint `0x0090` com criptografia de sessão ativa:

| Recurso | Formato do Payload em Bytes | Parâmetros e Significados |
| :--- | :--- | :--- |
| **Localização de Uso (Wear Location)** | `[0x06, 0x02, 0x00, loc]` | `loc = 0x00`: Pulso Esquerdo<br>`loc = 0x01`: Pulso Direito (calibra o acelerômetro para contagem de passos) |
| **Levantar Pulso (Lift Wrist)** | `[0x06, 0x05, mode, s_hr, s_mi, e_hr, e_mi, speed]` | `mode`: `0`=Desligado, `1`=Dia Todo, `2`=Agendado<br>`speed`: `0`=Normal, `1`=Rápido |
| **Modo Noturno (Night Mode)** | `[0x06, 0x0a, mode, s_hr, s_mi, e_hr, e_mi]` | `mode`: `0`=Desligado, `1`=Ao Pôr do Sol (Auto), `2`=Agendado (Reduz brilho da tela AMOLED) |
| **Não Perturbe (DND Mode)** | `[0x06, 0x0b, mode, s_hr, s_mi, e_hr, e_mi]` | `mode`: `0`=Desligado, `1`=Sempre Ativo, `2`=Inteligente (Auto-DND ao detectar sono), `3`=Agendado |
| **Idioma da Interface** | `[0x06, 0x08] + <código_iso>` | Strings ISO como `"pt_BR"`, `"en_US"`, `"es_ES"`, `"fr_FR"`, `"de_DE"`, `"it_IT"`, `"ru_RU"`, `"zh_CN"` |
| **Intervalo Cardíaco Periódico** | `[0x14, minutes]` em `0x2A39` | `minutes`: `1`, `5`, `10`, `30` (Ajusta o ciclo de medições periódicas contínuas) |

---

## 10. Métricas Avançadas: PAI, Estresse, SpO2 e Metas

### 10.1 Metas Diárias de Atividade Física (Passos & Calorias)
* **Endpoint:** `0x0090` (144)
* **Formato do Pacote:**
  `[0x06, 0x01, 0x00, step_goal_low, step_goal_high, cal_goal_low, cal_goal_high]`
* **Estrutura:** 7 bytes codificados em little-endian.
* **Comportamento:** Atualiza os anéis de meta diária no mostrador e ativa as animações de comemoração na tela da pulseira ao atingir o objetivo.

### 10.2 Pontuação PAI (Personal Activity Intelligence)
* **Endpoint:** `0x0090` (144)
* **Formato do Pacote:**
  `[0x01, 0x18, total_pai_low, total_pai_high, today_pai_low, today_pai_high]`
* **Estrutura:** 6 bytes em little-endian (`total_pai`: 0 a 999 acumulado nos últimos 7 dias; `today_pai`: 0 a 100 pontos conquistados no dia).
* **Comportamento:** Mantém o widget nativo de PAI sincronizado com o cálculo do servidor, motivando a manutenção de pontuação semanal acima de 100.

### 10.3 Monitoramento Contínuo e Medição de Estresse (HRV)
* **Ativação Contínua:** Envio de `[0x06, 0x12, enabled, interval_minutes]` no endpoint `0x0090`.
* **Aferição Manual:** O sensor PPG captura os microintervalos R-R entre picos de pulsação sanguínea (Heart Rate Variability). A variabilidade reduzida indica alta estimulação simpática (alto estresse), enquanto alta variabilidade indica controle parassimpático (relaxado).
* **Escala Oficial Huami:**
  * `0 a 29`: Relaxado (Estado calmo / repouso)
  * `30 a 59`: Leve (Atividade mental equilibrada)
  * `60 a 79`: Moderado (Tensão ou sobrecarga)
  * `80 a 100`: Alto (Estresse severo / fadiga aguda)

### 10.4 Oxímetro de Pulso (SpO2 — Saturação de Oxigênio)
* **Característica de Controle:** `00002a39-0000-1000-8000-00805f9b34fb` (Heart Rate Control Point)
* **Comando de Disparo:** `[0x15, 0x03, 0x01]` (Stop: `[0x15, 0x03, 0x00]`).
* **Retorno:** Notificação óptica no canal `0x2A37` com a leitura estabilizada de saturação arterial de oxigênio (`80%` a `100%`).
* **Procedimento:** Requer que o braço do usuário permaneça em repouso imóvel por aproximadamente 25 a 30 segundos.

---

## 11. Notificações, Chamadas e Localização do Dispositivo

### 11.1 Notificações de Display (BLE New Alert)
* **Habilitação:** Escrita de `[0x00, 0xFF]` em `00002a44-...` (Alert Notification Control Point).
* **Transmissão:** Escrita em `00002a46-...` (New Alert):
  `[categoria, contador] + <Título / Remetente>: <Corpo da Mensagem em UTF-8>`
  * Categorias: `0x03` = Alerta Prioritário / Chamada, `0x05` = Email / Notificação Geral, `0x01` = Mensagem Simples.

### 11.2 Localizar Dispositivo (Find Device) e Cancelamento
* **Iniciar Vibração:** Disparo combinado do alerta imediato (`0x2A06 = [0x02]`), Huami Alert (`0x0003 = [0x02]`) e CallSpec Incoming no canal chunk 0 (`[0x03, 0x00, 0x00, 0x00, 0x00, 0x00] + <Texto> + [0x00, 0x00, 0x00, 0x02]`).
* **Interromper Vibração (Stop Find):** Envio do comando de cancelamento `[0x03, 0x03, 0x00, 0x00, 0x00, 0x00]` no canal de controle e desativação de `0x2A06`.

---

## 12. Leitura de Telemetria e Bateria

### 12.1 Atividade do Dia (Passos, Metros, Calorias)
* **Característica:** `00000007-0000-3512-2118-0009af100700`
* **Formato:** 13 bytes binários:
  * `Bytes 1..4`: Passos totais acumulados no dia (`uint32LE`).
  * `Bytes 5..8`: Distância percorrida em metros (`uint32LE`).
  * `Bytes 9..12`: Calorias gastas em kcal (`uint32LE`).

### 12.2 Bateria Detalhada
* **Característica:** `00000006-0000-3512-2118-0009af100700`
  * `Byte 1`: Nível de carga (`0%` a `100%`).
  * `Byte 2`: Estado (`0x01` = Em uso/descarregando, `0x02` = Carregando, `0x03` = Carga Completa).
  * `Bytes 3..8`: Ano, Mês, Dia, Hora, Minuto, Segundo da última recarga total.
