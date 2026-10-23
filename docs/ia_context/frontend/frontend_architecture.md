# Arquitetura e Contexto do Frontend — MiBand 6 Server

## 🎨 Design, Estética e Organização

A Interface Web do **MiBand 6 Server** foi construída como uma Single Page Application (SPA) ultrarrápida utilizando **Vite**, **TypeScript**, **HTML5 semântico** e **Vanilla CSS3**. A ausência proposital de frameworks pesados (como React ou Angular) elimina overhead de processamento no navegador e viabiliza um bundle minúsculo servido eficientemente pelo `nginx:alpine` no Raspberry Pi 4.

- **Identidade Visual Premium:** O design segue diretrizes de padrão moderno com tema *Dark Mode* (`#0f172a`), cartões translúcidos com efeito *Glassmorphism* (`backdrop-filter: blur(12px)`), bordas suaves (`border-radius: 16px`), microanimações em CSS e tipografia limpa da família **Outfit** do Google Fonts.
- **Componentes Customizados:** O arquivo `src/custom-select.ts` fornece comboboxes estilizados e acessíveis, substituindo os elementos `<select>` nativos do navegador por dropdowns estilizados com o tema escuro.

---

## 📱 Módulos e Telas da Interface (`index.html`)

A aplicação divide-se em 6 abas de navegação gerenciadas dinamicamente:

### 1. Dashboard (`#tab-dashboard`)
Controlado por `src/main.ts`. Apresenta a visão executiva e em tempo real da saúde e do dispositivo:
* **Grid de Métricas Resumidas:**
  * **Passos Hoje:** Contador numérico, distância percorrida e barra de progresso dinâmica baseada na meta de passos diária configurada (ex: 8.000 passos).
  * **Frequência Cardíaca:** Última leitura registrada em BPM com destaque visual.
  * **Calorias Queimadas:** Total energético com barra de progresso em relação à meta de calorias.
  * **Bateria:** Percentual atual e barra de carga proporcional colorida.
  * **Oxigênio no Sangue (SpO2):** Nível de saturação arterial e classificação de integridade.
  * **Nível de Estresse:** Pontuação de 1 a 100 calculada a partir da variabilidade cardíaca (HRV) e badge de estado (Relaxado, Leve, Moderado, Alto).
  * **Pontuação PAI:** Exibição do escore semanal acumulado e pontos conquistados no dia atual.
* **Gráficos Interativos (Chart.js):**
  * Gráfico de evolução de passos ao longo do dia.
  * Gráfico de monitoramento contínuo de batimentos cardíacos.
* **Ações Rápidas:** Botões no cabeçalho superior para disparar *Sincronizar Agora* ou *Localizar Pulseira* (vibração física).

---

### 2. Histórico de Sincronizações (`#tab-history`)
* Tabela de auditoria completa (`.data-table`) consumindo `/api/sync/history`.
* Exibe data/hora da tentativa, MAC do dispositivo, status visual com badges coloridas (Sucesso / Erro), mensagem resumida e bloco de log com código de erro detalhado para depuração.

---

### 3. Gerenciador de Dispositivos (`#tab-devices`)
* **Scanner Bluetooth Ativo:** Dispara varredura nas antenas do Raspberry Pi listando dispositivos BLE próximos com endereço MAC, nome anunciado e indicador de força de sinal RSSI (dBm).
* **Cadastro e Configuração:** Formulário lateral para cadastrar ou editar o dispositivo, associar o nome, inserir a **Auth Key** de 32 hexadecimais e configurar os intervalos e horários de sincronização automática.
* **Lista de Pulseiras Pareadas:** Tabela de dispositivos cadastrados com opção de ativar/desativar e disparar sincronização imediata.

---

### 4. Integrações Meteorológicas & Clima (`#tab-integrations`)
* Seleção de provedores (Open-Meteo, OpenWeatherMap, WeatherAPI) e configuração de tokens de autenticação.
* Seletor geográfico com busca inteligente de cidades e botão de detecção automática por geolocalização do navegador.
* Painel de monitoramento do Redis em RAM, exibindo se o cache em memória está ativo ou operando em modo volátil.
* Tabela de histórico das previsões climáticas capturadas da web e enviadas para a pulseira.

---

### 5. Configurações da Pulseira (`#tab-band-settings`)
Controlado pelo módulo dedicado `src/band-settings-tab.ts`. Comunica-se com os endpoints `/api/band/settings`, `/sync` e `/read`:
* **Lembretes de Eventos:** Criação, edição e exclusão de lembretes que a pulseira exibirá com data e hora.
* **Alarmes (10 Slots Nativos):** Gerenciador de alarmes com ativação independente, seleção de dias da semana (Dom a Sáb), disparo único e modo soneca.
* **Relógio Mundial:** Adição de até 10 cidades mundiais com cálculo automático de fuso horário e relógio digital atualizado a cada segundo no navegador.
* **Gesto ao Levantar o Pulso (Lift Wrist):** Modos Desligado, O Dia Todo ou Horário Programado, com seleção de velocidade de resposta do display (Normal / Rápido).
* **Modo Noturno & Não Perturbe (DND):** Redução automática de brilho ao pôr do sol ou agendado, e ativação de DND Inteligente que silencia notificações ao detectar que o usuário dormiu.
* **Localização da Pulseira:** Calibração do acelerômetro selecionando Pulso Esquerdo ou Direito.
* **Idioma da Interface:** Troca instantânea do idioma do display para Português, Inglês, Espanhol, Francês, Alemão, Italiano, Russo ou Chinês.
* **Metas Diárias de Atividade:** Ajuste personalizado da meta de passos (passos/dia) e calorias (kcal/dia).
* **Monitoramento Contínuo de Estresse:** Ativação/desativação e seleção de intervalo de amostragem (5, 10 ou 30 minutos).
* **Barra de Ações Superior:** Botões para *Ler Alarmes da Pulseira* e *Salvar & Sincronizar Tudo* via BLE.

---

### 6. Laboratório de Testes (`#tab-test`)
Controlado por `src/test-tab.ts`. Um ambiente de diagnóstico isolado que não altera o histórico oficial do usuário:
* **Comunicação em Tempo Real (SSE):** Consome o endpoint `POST /api/test/stream` utilizando a API nativa `ReadableStream` do navegador, exibindo o progresso percentual e mensagens passo a passo.
* **Console Interativo de Logs:** Janela estilo terminal que renderiza logs com timestamps em milissegundos, níveis de severidade coloridos (`INFO`, `WARN`, `ERROR`, `OK`) e botões para limpar ou copiar logs.
* **Cards de Teste Individuais:**
  * Atividade Física (Passos, Metros, Calorias).
  * Nível Detalhado e Status de Carga da Bateria.
  * Medição sob Demanda de Batimentos Cardíacos (PPG).
  * Oxímetro sob Demanda (SpO2 com avaliação clínica).
  * Medição sob Demanda de Estresse (HRV e escore de 1 a 100).
  * Envio de Metas de Atividade Física.
  * Transmissão de Escore PAI (Total e Hoje).
  * Verificação e Ajuste de Desvio de Relógio da Pulseira.
  * Informações de Fabricante e Hardware (DIS).
  * Consulta e Leitura Direta de Alarmes Armazenados.
  * Envio Personalizado de Previsão do Tempo com editor de cartões para os 7 dias.
  * Disparo de Notificações com Categorias e Título/Corpo customizados.
  * Teste de Vibração Háptica (Localização de Dispositivo).
