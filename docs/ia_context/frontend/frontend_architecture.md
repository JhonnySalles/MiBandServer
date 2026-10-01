# Arquitetura e Contexto do Frontend

## 🎨 Design, Estética e Organização

A Interface foi esculpida utilizando **Vanilla TypeScript, HTML5 semântico e puro CSS3**. Não há frameworks UI (como React ou Vue), reduzindo complexidades de builds ou dependências legadas na máquina embarcada.

- A escolha de focar em **Vite** viabilizou um processo de bundler microscópico, excelente HMR (Hot Module Replacement) e empacotamento que o `nginx:alpine` entrega com mínimo uso de recursos no Raspberry.
- O design atende requisições de qualidade premium (UX de primeiro mundo): `Glassmorphism`, fundo _Dark Mode_ (`#0f172a`), bordas radiadas (`16px`, `10px`), além da fonte sem-serifa moderna **Outfit** do Google Fonts, dando uma silhueta limpa aos textos.

## 📱 Estruturas e Telas (index.html & main.ts)

A interface flui em um layout de Single Page Application controlada por abas ("Tabs"). As lógicas para manipulação do DOM e interceptação das chamadas de API ficam hospedadas inteiramente no `src/main.ts`.

### Módulo: Dashboard (`#tab-dashboard`)
Exibe métricas chave resumidas no alto da interface.
- Cards rápidos usando grids dinâmicos (Passos, Frequência Cardíaca, Calorias, Bateria).
- Gráficos gerados on-the-fly pelo `Chart.js` lendo requisições históricas para plotar linhas evolutivas do dia com visual estilizado na própria cor do tema (roxo principal para passos, vermelho alerta para os batimentos).
- Permite o disparo de comandos ativos como **Sincronizar Agora** ou **Enviar Previsão do Tempo** manualmente preenchida pelo usuário ou via auto-fetch da internet.

### Módulo: Histórico (`#tab-history`)
- Área de auditoria em forma tabular (`.data-table`), preenchida dinamicamente lendo o `/api/sync/history`. Traz timestamps, identificação da pulseira impactada, status com _tags_ estilizadas e detalhes de log técnico em bloco tipo código (`<code>`).

### Módulo: Gerenciador de Dispositivos (`#tab-devices`)
- Área focada na capacidade nativa do hardware Bluetooth de fazer *Scanner*. Um botão emite ordem de scan para antenas próximas e lista as pulseiras descobertas junto ao seu sinal RSSI (dBm).
- Clicar sobre um item descoberto preenche um formulário lateral de setup CRUD. A tabela de pulseiras salvas permite que com um botão cada uma inicie sincronização própria ou seja deletada do ecossistema.

### Módulo: Integrações e Clima (`#tab-integrations`)
- Uma dashboard administrativa para o backend gerenciar seus consumos da web.
- O formulário capta, através de um dropdown de *provedores*, a seleção da API meteorológica, pede os tokens e coordenadas (lat/lon) e customiza o tempo que essas consultas devem viver na RAM.
- Embaixo, existe o feedback "⚡ Banco em Memória & Proteção do SD Card", consumindo endpoint de validação em tempo real para exibir se o Redis está operante ou em fallback local de Python.
