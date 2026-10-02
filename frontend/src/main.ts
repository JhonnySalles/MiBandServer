// Obter a URL base da API a partir de envs injetadas ou inferir pela origem / padrão 8190
const API_URL = (import.meta as any).env?.VITE_API_URL || 
  (typeof window !== 'undefined' && window.location.hostname 
    ? `${window.location.protocol}//${window.location.hostname}:8190` 
    : 'http://localhost:8190');

declare const Chart: any;

let stepsChartInstance: any = null;
let heartChartInstance: any = null;

interface DeviceConfig {
  id?: number;
  mac_address: string;
  device_name: string;
  auth_key?: string;
  sync_interval_hours?: number;
  sync_intervals: string;
  auto_weather: boolean;
  is_active: boolean;
  last_sync_time?: string;
}

interface IntegrationConfig {
  id?: number;
  weather_provider: string;
  weather_api_token?: string;
  weather_city: string;
  latitude?: number;
  longitude?: number;
  cache_ttl_minutes: number;
}

interface ActivityMetrics {
  steps: number;
  distance_meters: number;
  calories: number;
  heart_rate: number | null;
  battery_level: number | null;
  timestamp: string;
}

interface SyncLog {
  id: number;
  device_mac?: string;
  timestamp: string;
  status: string;
  message: string;
  details: string;
}

let currentScheduleTimes: string[] = ['08:00', '12:00', '18:00', '22:00'];

function renderScheduleBadges() {
  const container = document.getElementById('schedule-times-container');
  const hiddenInput = document.getElementById('cfg-intervals') as HTMLInputElement;
  if (!container) return;

  if (currentScheduleTimes.length === 0) {
    container.innerHTML = '<span class="text-muted text-sm">Nenhum horário fixo adicionado.</span>';
    if (hiddenInput) hiddenInput.value = '';
    return;
  }

  // Ordenar horários
  currentScheduleTimes.sort();
  if (hiddenInput) hiddenInput.value = currentScheduleTimes.join(', ');

  container.innerHTML = currentScheduleTimes
    .map(
      (time, idx) => `
      <div class="schedule-badge-item">
        <span>⏰ ${time}</span>
        <button type="button" class="btn-remove-badge" onclick="window.removeScheduleTime(${idx})" title="Remover">✕</button>
      </div>
    `
    )
    .join('');
}

(window as any).removeScheduleTime = (index: number) => {
  currentScheduleTimes.splice(index, 1);
  renderScheduleBadges();
};

// Inicialização de Tabs
function initTabs() {
  const navButtons = document.querySelectorAll('.nav-item');
  const tabContents = document.querySelectorAll('.tab-content');
  const titleEl = document.getElementById('page-title');
  const subtitleEl = document.getElementById('page-subtitle');

  const titles: Record<string, { title: string; sub: string }> = {
    dashboard: { title: 'Painel de Métricas', sub: 'Sincronização em tempo real do Raspberry Pi com sua Mi Band' },
    history: { title: 'Histórico de Atividades', sub: 'Registros de sincronizações e leituras anteriores' },
    devices: { title: 'Gerenciador de Dispositivos', sub: 'Pareamento Bluetooth, múltiplos aparelhos e agendamentos' },
    integrations: { title: 'Integrações & Cache', sub: 'Tokens meteorológicos, cache em memória RAM e proteção do SD' }
  };

  navButtons.forEach((btn) => {
    btn.addEventListener('click', () => {
      const tabKey = btn.getAttribute('data-tab');
      if (!tabKey) return;

      navButtons.forEach((b) => b.classList.remove('active'));
      tabContents.forEach((c) => c.classList.remove('active'));

      btn.classList.add('active');
      document.getElementById(`tab-${tabKey}`)?.classList.add('active');

      if (titles[tabKey] && titleEl && subtitleEl) {
        titleEl.textContent = titles[tabKey].title;
        subtitleEl.textContent = titles[tabKey].sub;
      }

      if (tabKey === 'dashboard') {
        loadDashboard();
        loadDashboardCharts();
      }
      if (tabKey === 'history') loadHistory();
      if (tabKey === 'devices') {
        loadDevicesList();
        renderScheduleBadges();
      }
      if (tabKey === 'integrations') {
        loadIntegrations();
        loadWeatherPreview();
      }
    });
  });
}

// Notificações Toast
function showNotification(msg: string, type: 'success' | 'error' = 'success') {
  const notif = document.getElementById('notification');
  if (!notif) return;
  notif.textContent = msg;
  notif.className = `notification ${type}`;
  setTimeout(() => {
    notif.className = 'notification hidden';
  }, 4000);
}

// Checar status do sistema e Redis
async function checkSystemStatus() {
  try {
    const res = await fetch(`${API_URL}/api/status`);
    if (!res.ok) return;
    const data = await res.json();
    const redisIndicator = document.getElementById('redis-indicator');
    const redisText = document.getElementById('redis-status-text');
    if (data.redis_connected) {
      if (redisIndicator) redisIndicator.className = 'status-indicator online';
      if (redisText) redisText.textContent = 'Ativo / Em Memória RAM';
    } else {
      if (redisIndicator) redisIndicator.className = 'status-indicator';
      if (redisText) redisText.textContent = 'Modo Local Volátil';
    }
  } catch (err) {
    console.error('Erro ao verificar status:', err);
  }
}

// Carregar Métricas do Dashboard e Atualizar Gráficos
async function loadDashboard() {
  try {
    const res = await fetch(`${API_URL}/api/metrics/latest`);
    if (!res.ok) return;
    const data: ActivityMetrics = await res.json();
    if (!data) return;

    const stepsEl = document.getElementById('val-steps');
    const distEl = document.getElementById('val-distance');
    const heartEl = document.getElementById('val-heart');
    const calEl = document.getElementById('val-calories');
    const batEl = document.getElementById('val-battery');
    const batBar = document.getElementById('battery-level-bar');

    if (stepsEl) stepsEl.textContent = (data.steps || 0).toLocaleString('pt-BR');
    if (distEl) distEl.textContent = `${((data.distance_meters || 0) / 1000).toFixed(2)} km percorridos`;
    if (heartEl) heartEl.innerHTML = `${data.heart_rate ?? '--'} <small>BPM</small>`;
    if (calEl) calEl.innerHTML = `${data.calories || 0} <small>kcal</small>`;
    if (batEl) batEl.textContent = `${data.battery_level ?? '--'}%`;
    if (batBar && data.battery_level !== null) batBar.style.width = `${data.battery_level}%`;

    loadDashboardCharts();
  } catch (err) {
    console.error('Erro ao buscar métricas:', err);
  }
}

// Gráficos Chart.js
async function loadDashboardCharts() {
  try {
    const res = await fetch(`${API_URL}/api/metrics/history?limit=10`);
    if (!res.ok) return;
    let list: ActivityMetrics[] = await res.json();
    if (!list || list.length === 0) return;

    list = list.reverse(); // Ordem cronológica

    const labels = list.map((m) => new Date(m.timestamp).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }));
    const stepsData = list.map((m) => m.steps);
    const heartData = list.map((m) => m.heart_rate ?? 70);

    // Gráfico de Passos
    const ctxSteps = (document.getElementById('stepsChart') as HTMLCanvasElement)?.getContext('2d');
    if (ctxSteps && typeof Chart !== 'undefined') {
      if (stepsChartInstance) stepsChartInstance.destroy();
      stepsChartInstance = new Chart(ctxSteps, {
        type: 'line',
        data: {
          labels,
          datasets: [
            {
              label: 'Passos',
              data: stepsData,
              borderColor: '#6366f1',
              backgroundColor: 'rgba(99, 102, 241, 0.15)',
              tension: 0.35,
              fill: true,
              borderWidth: 2
            }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            x: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#94a3b8' } },
            y: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#94a3b8' } }
          }
        }
      });
    }

    // Gráfico de Batimentos Cardíacos
    const ctxHeart = (document.getElementById('heartChart') as HTMLCanvasElement)?.getContext('2d');
    if (ctxHeart && typeof Chart !== 'undefined') {
      if (heartChartInstance) heartChartInstance.destroy();
      heartChartInstance = new Chart(ctxHeart, {
        type: 'line',
        data: {
          labels,
          datasets: [
            {
              label: 'BPM',
              data: heartData,
              borderColor: '#ef4444',
              backgroundColor: 'rgba(239, 68, 68, 0.15)',
              tension: 0.35,
              fill: true,
              borderWidth: 2
            }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            x: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#94a3b8' } },
            y: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#94a3b8' } }
          }
        }
      });
    }
  } catch (e) {
    console.error('Erro ao renderizar gráficos:', e);
  }
}

// Carregar Lista de Dispositivos (Multi-device)
async function loadDevicesList() {
  const tbody = document.getElementById('devices-table-body');
  if (!tbody) return;

  try {
    const res = await fetch(`${API_URL}/api/devices`);
    if (!res.ok) return;
    const devices: DeviceConfig[] = await res.json();

    if (devices.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" class="text-center">Nenhum dispositivo cadastrado. Cadastre ao lado ou escaneie o BLE.</td></tr>';
      return;
    }

    // Atualiza sidebar com o primeiro dispositivo ativo
    const primary = devices[0];
    const sideName = document.getElementById('sidebar-device-name');
    const sideMac = document.getElementById('sidebar-device-mac');
    if (sideName) sideName.textContent = primary.device_name || 'Mi Smart Band 6';
    if (sideMac) sideMac.textContent = primary.mac_address;

    // Atualiza badges da Dashboard
    const badgesContainer = document.getElementById('sync-schedule-badges');
    if (badgesContainer) {
      const intervalBadge = `<span class="badge badge-pill" style="border-color: #6366f1;">⏱️ A cada ${primary.sync_interval_hours || 1}h</span>`;
      const timeBadges = primary.sync_intervals
        ? primary.sync_intervals.split(',').map((t) => `<span class="badge badge-pill">${t.trim()}</span>`).join('')
        : '';
      badgesContainer.innerHTML = intervalBadge + timeBadges;
    }

    tbody.innerHTML = devices
      .map(
        (dev) => `
        <tr>
          <td><strong>${dev.device_name}</strong></td>
          <td><code>${dev.mac_address}</code></td>
          <td>
            <div style="font-size: 0.8rem;">
              <div><strong>Intervalo:</strong> a cada ${dev.sync_interval_hours || 1}h</div>
              <div class="text-muted"><strong>Fixos:</strong> ${dev.sync_intervals || 'Nenhum'}</div>
            </div>
          </td>
          <td>
            ${
              dev.last_sync_time
                ? `<span class="text-sm" title="${dev.last_sync_time}">${new Date(dev.last_sync_time).toLocaleString('pt-BR')}</span>`
                : '<span class="text-muted text-sm">Nunca</span>'
            }
          </td>
          <td>${dev.auto_weather ? '<span class="status-tag success">Sim</span>' : '<span class="status-tag">Não</span>'}</td>
          <td>
            <div class="d-flex gap-2">
              <button class="btn btn-secondary btn-sm" onclick="window.syncSingleDevice('${dev.mac_address}')" title="Sincronizar">🔄</button>
              <button class="btn btn-secondary btn-sm" onclick='window.editDevice(${JSON.stringify(dev)})' title="Editar">✏️</button>
              <button class="btn btn-danger btn-sm" onclick="window.deleteDevice('${dev.mac_address}')" title="Excluir">🗑️</button>
            </div>
          </td>
        </tr>
      `
      )
      .join('');
  } catch (err) {
    tbody.innerHTML = '<tr><td colspan="6" class="text-center">Erro ao carregar lista de dispositivos.</td></tr>';
  }
}

// Carregar Configuração de Integrações
async function loadIntegrations() {
  try {
    const res = await fetch(`${API_URL}/api/integrations`);
    if (!res.ok) return;
    const config: IntegrationConfig = await res.json();
    if (!config) return;

    const provInput = document.getElementById('int-provider') as HTMLSelectElement;
    const tokenInput = document.getElementById('int-token') as HTMLInputElement;
    const cityInput = document.getElementById('int-city') as HTMLInputElement;
    const latInput = document.getElementById('int-lat') as HTMLInputElement;
    const lonInput = document.getElementById('int-lon') as HTMLInputElement;
    const ttlInput = document.getElementById('int-ttl') as HTMLInputElement;

    if (provInput) provInput.value = config.weather_provider || 'open-meteo';
    if (tokenInput) tokenInput.value = config.weather_api_token || '';
    if (cityInput) cityInput.value = config.weather_city || 'São Paulo';
    if (latInput) latInput.value = (config.latitude ?? -23.5505).toString();
    if (lonInput) lonInput.value = (config.longitude ?? -46.6333).toString();
    if (ttlInput) ttlInput.value = (config.cache_ttl_minutes ?? 30).toString();
  } catch (err) {
    console.error('Erro ao carregar integrações:', err);
  }
}

// Carregar Prévia do Clima Estendido (Forecast)
async function loadWeatherPreview() {
  const container = document.getElementById('weather-preview-content');
  if (!container) return;
  container.innerHTML = '<p class="text-muted">Consultando meteorologia estendida...</p>';

  try {
    const res = await fetch(`${API_URL}/api/weather/current`);
    if (!res.ok) return;
    const data = await res.json();
    
    const cur = data.current || data;
    const daily = data.daily_forecast || [];

    let forecastHtml = '';
    if (daily.length > 0) {
      forecastHtml = `
        <div class="forecast-days-grid">
          ${daily
            .map(
              (f: any) => `
            <div class="forecast-day-card">
              <div class="day-label">${f.day || f.date}</div>
              <div class="day-temp">${f.temp_max}° / ${f.temp_min}°</div>
              <div class="day-cond">${f.condition}</div>
            </div>
          `
            )
            .join('')}
        </div>
      `;
    }

    container.innerHTML = `
      <div class="d-flex align-center gap-3">
        <span style="font-size: 2.2rem;">🌤️</span>
        <div>
          <div style="font-size: 1.25rem; font-weight: 700;">${cur.temp}°C - ${cur.condition}</div>
          <div class="text-muted text-sm">Umidade: ${cur.humidity || 50}% | Provedor: <strong>${data.provider || cur.provider || 'Open-Meteo'}</strong></div>
        </div>
      </div>
      ${forecastHtml}
    `;
  } catch (err) {
    container.innerHTML = '<p class="text-muted">Não foi possível carregar a previsão estendida do clima.</p>';
  }
}

// Carregar Histórico
async function loadHistory() {
  const tbody = document.getElementById('history-table-body');
  if (!tbody) return;

  try {
    const res = await fetch(`${API_URL}/api/sync/history`);
    if (!res.ok) return;
    const list: SyncLog[] = await res.json();

    if (list.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" class="text-center">Nenhum registro ainda.</td></tr>';
      return;
    }

    tbody.innerHTML = list
      .map(
        (log) => `
        <tr>
          <td>${new Date(log.timestamp).toLocaleString('pt-BR')}</td>
          <td><code>${log.device_mac || 'Principal'}</code></td>
          <td><span class="status-tag ${log.status.toLowerCase()}">${log.status}</span></td>
          <td>${log.message || '-'}</td>
          <td><code>${log.details || '-'}</code></td>
        </tr>
      `
      )
      .join('');
  } catch (err) {
    tbody.innerHTML = '<tr><td colspan="5" class="text-center">Erro ao carregar histórico.</td></tr>';
  }
}

// Funções Globais expostas para as ações dos botões
(window as any).syncSingleDevice = async (mac: string) => {
  showNotification(`Sincronizando dispositivo ${mac}...`, 'success');
  try {
    const res = await fetch(`${API_URL}/api/sync`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mac_address: mac })
    });
    const data = await res.json();
    if (data.status === 'SUCCESS') {
      showNotification('Sincronização e envio de clima concluídos com sucesso!', 'success');
      loadDashboard();
      loadDevicesList();
    } else {
      showNotification(data.message || 'Falha ao sincronizar dispositivo.', 'error');
    }
  } catch (err) {
    showNotification('Erro ao conectar com a API.', 'error');
  }
};

(window as any).deleteDevice = async (mac: string) => {
  if (!confirm(`Deseja realmente remover o dispositivo ${mac}?`)) return;
  try {
    const res = await fetch(`${API_URL}/api/devices/${mac}`, { method: 'DELETE' });
    if (res.ok) {
      showNotification('Dispositivo removido.', 'success');
      loadDevicesList();
    } else {
      showNotification('Falha ao remover dispositivo.', 'error');
    }
  } catch (err) {
    showNotification('Erro de rede ao remover.', 'error');
  }
};

(window as any).editDevice = (dev: DeviceConfig) => {
  const macInput = document.getElementById('cfg-mac') as HTMLInputElement;
  const nameInput = document.getElementById('cfg-name') as HTMLInputElement;
  const authInput = document.getElementById('cfg-auth') as HTMLInputElement;
  const intervalHoursInput = document.getElementById('cfg-interval-hours') as HTMLInputElement;
  const intInput = document.getElementById('cfg-intervals') as HTMLInputElement;
  const weatherCheck = document.getElementById('cfg-auto-weather') as HTMLInputElement;
  const cancelBtn = document.getElementById('btn-cancel-edit');
  const title = document.getElementById('form-device-title');

  if (macInput) macInput.value = dev.mac_address;
  if (nameInput) nameInput.value = dev.device_name;
  if (authInput) authInput.value = dev.auth_key || '';
  if (intervalHoursInput) intervalHoursInput.value = (dev.sync_interval_hours || 1).toString();
  if (intInput) intInput.value = dev.sync_intervals;
  if (weatherCheck) weatherCheck.checked = dev.auto_weather;

  // Atualizar lista de horários fixos
  currentScheduleTimes = dev.sync_intervals
    ? dev.sync_intervals.split(',').map((t) => t.trim()).filter((t) => !!t)
    : [];
  renderScheduleBadges();

  if (cancelBtn) cancelBtn.classList.remove('hidden');
  if (title) title.textContent = `✏️ Editar Pulseira (${dev.device_name})`;
};

(window as any).selectBleDevice = (mac: string, name: string) => {
  const macInput = document.getElementById('cfg-mac') as HTMLInputElement;
  const nameInput = document.getElementById('cfg-name') as HTMLInputElement;
  if (macInput) macInput.value = mac;
  if (nameInput) nameInput.value = name;
  showNotification(`Dispositivo selecionado: ${name}`, 'success');
};

// Configurar Eventos
function setupEventListeners() {
  // Adicionar horário específico na Grid
  document.getElementById('btn-add-schedule-time')?.addEventListener('click', () => {
    const timeInput = document.getElementById('new-schedule-time') as HTMLInputElement;
    if (!timeInput || !timeInput.value) return;
    const timeVal = timeInput.value;
    if (!currentScheduleTimes.includes(timeVal)) {
      currentScheduleTimes.push(timeVal);
      renderScheduleBadges();
      showNotification(`Horário ${timeVal} adicionado!`, 'success');
    } else {
      showNotification('Horário já cadastrado.', 'error');
    }
  });

  // Sincronizar Geral
  document.getElementById('btn-sync-now')?.addEventListener('click', async () => {
    showNotification('Iniciando sincronização e clima via Bluetooth...', 'success');
    try {
      const res = await fetch(`${API_URL}/api/sync`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) });
      const data = await res.json();
      if (data.status === 'SUCCESS') {
        showNotification('Sincronização concluída com sucesso!', 'success');
        loadDashboard();
        loadDevicesList();
      } else {
        showNotification(data.message || 'Falha ao sincronizar com o relógio.', 'error');
      }
    } catch (e) {
      showNotification('Erro de comunicação com o servidor.', 'error');
    }
  });

  // Localizar Pulseira (Vibrar)
  document.getElementById('btn-find-band')?.addEventListener('click', async () => {
    showNotification('Enviando sinal de vibração...', 'success');
    try {
      const res = await fetch(`${API_URL}/api/vibrate`, { method: 'POST' });
      if (res.ok) {
        showNotification('Alerta de vibração enviado!', 'success');
      } else {
        showNotification('Falha ao enviar vibração.', 'error');
      }
    } catch (e) {
      showNotification('Erro de comunicação com o servidor.', 'error');
    }
  });

  // Escanear BLE
  document.getElementById('btn-scan-ble')?.addEventListener('click', async () => {
    const list = document.getElementById('ble-devices-list');
    if (list) list.innerHTML = '<li class="empty-state">Escaneando antenas Bluetooth... aguarde</li>';
    try {
      const res = await fetch(`${API_URL}/api/ble/scan`);
      const data = await res.json();
      if (list) {
        if (!data.devices || data.devices.length === 0) {
          list.innerHTML = '<li class="empty-state">Nenhum dispositivo BLE encontrado por perto.</li>';
          return;
        }
        list.innerHTML = data.devices
          .map(
            (d: any) => `
            <li class="device-item">
              <div class="device-item-info">
                <strong>${d.name}</strong>
                <span>MAC: ${d.address} | RSSI: ${d.rssi} dBm</span>
              </div>
              <button class="btn btn-secondary" onclick="window.selectBleDevice('${d.address}', '${d.name}')">Selecionar</button>
            </li>
          `
          )
          .join('');
      }
    } catch (e) {
      if (list) list.innerHTML = '<li class="empty-state">Erro ao escanear dispositivos.</li>';
    }
  });

  // Salvar Dispositivo
  document.getElementById('form-config')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const mac = (document.getElementById('cfg-mac') as HTMLInputElement).value;
    const name = (document.getElementById('cfg-name') as HTMLInputElement).value;
    const auth = (document.getElementById('cfg-auth') as HTMLInputElement).value;
    const intervalHours = parseInt((document.getElementById('cfg-interval-hours') as HTMLInputElement).value, 10) || 1;
    const intervals = currentScheduleTimes.join(', ');
    const autoWeather = (document.getElementById('cfg-auto-weather') as HTMLInputElement).checked;

    try {
      const res = await fetch(`${API_URL}/api/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mac_address: mac,
          device_name: name,
          auth_key: auth,
          sync_interval_hours: intervalHours,
          sync_intervals: intervals,
          auto_weather: autoWeather
        })
      });
      if (res.ok) {
        showNotification('Dispositivo e agendamentos salvos com sucesso!', 'success');
        loadDevicesList();
        (document.getElementById('btn-cancel-edit') as HTMLElement)?.classList.add('hidden');
        (document.getElementById('form-device-title') as HTMLElement).textContent = '➕ Configurar Dispositivo';
      } else {
        showNotification('Falha ao salvar dispositivo.', 'error');
      }
    } catch (err) {
      showNotification('Erro na requisição ao servidor.', 'error');
    }
  });

  // Cancelar Edição
  document.getElementById('btn-cancel-edit')?.addEventListener('click', () => {
    (document.getElementById('form-config') as HTMLFormElement).reset();
    currentScheduleTimes = ['08:00', '12:00', '18:00', '22:00'];
    renderScheduleBadges();
    (document.getElementById('btn-cancel-edit') as HTMLElement).classList.add('hidden');
    (document.getElementById('form-device-title') as HTMLElement).textContent = '➕ Configurar Dispositivo';
  });

  // Salvar Integrações de Clima e Tokens
  document.getElementById('form-integrations')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const provider = (document.getElementById('int-provider') as HTMLSelectElement).value;
    const token = (document.getElementById('int-token') as HTMLInputElement).value;
    const city = (document.getElementById('int-city') as HTMLInputElement).value;
    const lat = parseFloat((document.getElementById('int-lat') as HTMLInputElement).value);
    const lon = parseFloat((document.getElementById('int-lon') as HTMLInputElement).value);
    const ttl = parseInt((document.getElementById('int-ttl') as HTMLInputElement).value, 10);

    try {
      const res = await fetch(`${API_URL}/api/integrations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          weather_provider: provider,
          weather_api_token: token,
          weather_city: city,
          latitude: lat,
          longitude: lon,
          cache_ttl_minutes: ttl
        })
      });
      if (res.ok) {
        showNotification('Integrações e tokens salvos com sucesso!', 'success');
        loadWeatherPreview();
      } else {
        showNotification('Erro ao salvar integrações.', 'error');
      }
    } catch (err) {
      showNotification('Falha ao se comunicar com o servidor.', 'error');
    }
  });

  // Atualizar Prévia do Clima
  document.getElementById('btn-refresh-weather-preview')?.addEventListener('click', () => {
    loadWeatherPreview();
  });

  // Enviar Clima Manual
  document.getElementById('form-weather')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const temp = parseInt((document.getElementById('weather-temp') as HTMLInputElement).value, 10);
    const cond = (document.getElementById('weather-condition') as HTMLInputElement).value;

    try {
      const res = await fetch(`${API_URL}/api/weather`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ temp, condition: cond, auto_fetch: false })
      });
      if (res.ok) {
        showNotification(`Clima (${temp}°C, ${cond}) enviado para a Mi Band!`, 'success');
      } else {
        showNotification('Erro ao enviar clima.', 'error');
      }
    } catch (e) {
      showNotification('Falha ao se comunicar com a API.', 'error');
    }
  });

  // Enviar Clima Automático da Internet
  document.getElementById('btn-auto-weather')?.addEventListener('click', async () => {
    showNotification('Consultando clima via integrações configuradas e enviando...', 'success');
    try {
      const res = await fetch(`${API_URL}/api/weather`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ auto_fetch: true })
      });
      const data = await res.json();
      if (res.ok && data.success) {
        showNotification(`Clima atualizado: ${data.temp}°C (${data.condition})!`, 'success');
      } else {
        showNotification('Falha ao enviar clima automático.', 'error');
      }
    } catch (e) {
      showNotification('Erro de comunicação com o servidor.', 'error');
    }
  });
}

// Iniciar tudo ao carregar
window.addEventListener('DOMContentLoaded', () => {
  initTabs();
  setupEventListeners();
  renderScheduleBadges();
  checkSystemStatus();
  loadDevicesList();
  loadDashboard();
});


