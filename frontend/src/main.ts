import { initTestTab } from './test-tab';
import { initBandSettingsTab, loadBandSettings } from './band-settings-tab';
import { initCustomSelects, syncCustomSelect } from './custom-select';


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

let bleScanTimer: any = null;
let isBleScanning = false;
let isAutoScanActive = true;

async function performBleScan() {
  if (isBleScanning || !isAutoScanActive) return;
  const list = document.getElementById('ble-devices-list');
  
  isBleScanning = true;
  try {
    const res = await fetch(`${API_URL}/api/ble/scan`);
    if (!res.ok) throw new Error('Falha ao escanear');
    const data = await res.json();
    
    if (list && isAutoScanActive) {
      if (!data.devices || data.devices.length === 0) {
        list.innerHTML = '<li class="empty-state">Nenhum dispositivo BLE detectado por perto no momento.</li>';
      } else {
        list.innerHTML = data.devices
          .map(
            (d: any) => `
            <li class="device-item">
              <div class="device-item-info">
                <strong>${d.name}</strong>
                <span>MAC: <code>${d.address}</code> | Sinal: ${d.rssi} dBm</span>
              </div>
              <button class="btn btn-secondary btn-sm" onclick="window.selectBleDevice('${d.address}', '${d.name}')">Selecionar</button>
            </li>
          `
          )
          .join('');
      }
    }
  } catch (e) {
    if (list && isAutoScanActive && list.children.length === 0) {
      list.innerHTML = '<li class="empty-state">Aguardando sinal do adaptador Bluetooth...</li>';
    }
  } finally {
    isBleScanning = false;
  }
}

function startAutoBleScan() {
  stopAutoBleScan();
  isAutoScanActive = true;
  const badge = document.getElementById('ble-radar-badge');
  const btnToggle = document.getElementById('btn-toggle-auto-scan');
  if (badge) {
    badge.className = 'badge badge-radar active';
    badge.innerHTML = '<span class="pulse-dot"></span> Busca Automática Ativa';
  }
  if (btnToggle) btnToggle.textContent = '⏸️ Pausar';

  performBleScan(); // Primeira execução imediata
  bleScanTimer = setInterval(performBleScan, 4500); // Repete a cada 4.5s
}

function stopAutoBleScan() {
  if (bleScanTimer) {
    clearInterval(bleScanTimer);
    bleScanTimer = null;
  }
}

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
    integrations: { title: 'Previsão do Tempo & Clima', sub: 'Previsão de 7 dias da semana, histórico climático e provedores de meteorologia' },
    'band-settings': { title: 'Configurações da Pulseira', sub: 'Lembretes, alarmes, relógio mundial, gestos de pulso, modo noturno e idioma da Mi Band 6' },
    test: { title: 'Laboratório de Testes & Diagnóstico', sub: 'Testes isolados de comunicação e envio de dados para a Mi Band' }
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

      // Ciclo de vida do Scanner BLE: Só roda na aba de Dispositivos
      if (tabKey === 'devices') {
        loadDevicesList();
        renderScheduleBadges();
        startAutoBleScan();
      } else {
        stopAutoBleScan();
      }

      if (tabKey === 'dashboard') {
        loadDashboard();
        loadDashboardCharts();
      }
      if (tabKey === 'history') loadHistory();
      if (tabKey === 'integrations') {
        loadIntegrations();
        loadWeatherPreview();
        loadWeatherHistory();
      }
      if (tabKey === 'band-settings') {
        loadBandSettings();
      }
    });
  });

  // Pausar varredura se o usuário minimizar a janela ou mudar de aba no navegador
  document.addEventListener('visibilitychange', () => {
    const activeTab = document.querySelector('.nav-item.active')?.getAttribute('data-tab');
    if (document.hidden) {
      stopAutoBleScan();
    } else if (activeTab === 'devices' && isAutoScanActive) {
      startAutoBleScan();
    }
  });
}

// Notificações Toast
function showNotification(msg: string, type: 'success' | 'error' | 'info' = 'success') {
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
    loadDashboardWeather();
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

// Atualizar exibição visual da cidade selecionada
function updateSelectedCityDisplay(city: string, lat: number, lon: number, provider?: string) {
  const nameEl = document.getElementById('selected-city-name');
  const coordsEl = document.getElementById('selected-city-coords');
  const badgeEl = document.getElementById('selected-city-provider-badge');
  const deviceCityLabel = document.getElementById('device-weather-city-label');
  const searchInput = document.getElementById('city-search-input') as HTMLInputElement;
  const cityInput = document.getElementById('int-city') as HTMLInputElement;
  const latInput = document.getElementById('int-lat') as HTMLInputElement;
  const lonInput = document.getElementById('int-lon') as HTMLInputElement;

  if (nameEl) nameEl.textContent = city;
  if (coordsEl) coordsEl.textContent = `Latitude: ${Number(lat).toFixed(4)} | Longitude: ${Number(lon).toFixed(4)}`;
  if (badgeEl && provider) {
    const provNames: Record<string, string> = {
      'open-meteo': 'Open-Meteo',
      'openweathermap': 'OpenWeatherMap',
      'weatherapi': 'WeatherAPI'
    };
    badgeEl.textContent = provNames[provider] || provider;
  }
  if (deviceCityLabel) deviceCityLabel.textContent = city;

  if (cityInput) cityInput.value = city;
  if (latInput) latInput.value = lat.toString();
  if (lonInput) lonInput.value = lon.toString();
  if (searchInput && !searchInput.value) searchInput.value = city;
}

// Inicializar Seletor Inteligente de Cidades & Detecção de Localização
function initCitySelector() {
  const searchInput = document.getElementById('city-search-input') as HTMLInputElement;
  const dropdown = document.getElementById('city-dropdown') as HTMLElement;
  const spinner = document.getElementById('city-search-spinner');
  const btnDetect = document.getElementById('btn-detect-location') as HTMLButtonElement;
  const btnDetectText = document.getElementById('btn-detect-location-text');
  const providerSelect = document.getElementById('int-provider') as HTMLSelectElement;
  const btnGotoWeather = document.getElementById('btn-goto-weather-config');

  if (!searchInput || !dropdown) return;

  let searchTimeout: any = null;
  let currentResults: any[] = [];
  let focusedIndex = -1;

  // Busca com debounce
  searchInput.addEventListener('input', () => {
    const query = searchInput.value.trim();
    clearTimeout(searchTimeout);

    if (query.length < 2) {
      dropdown.classList.remove('show');
      dropdown.innerHTML = '';
      if (spinner) spinner.classList.remove('active');
      return;
    }

    if (spinner) spinner.classList.add('active');
    searchTimeout = setTimeout(async () => {
      try {
        const prov = providerSelect ? providerSelect.value : 'open-meteo';
        const res = await fetch(`${API_URL}/api/weather/cities/search?query=${encodeURIComponent(query)}&provider=${encodeURIComponent(prov)}`);
        if (!res.ok) throw new Error('Falha na busca');
        const results = await res.json();
        currentResults = results;
        focusedIndex = -1;

        if (results.length === 0) {
          dropdown.innerHTML = '<div class="city-dropdown-empty">Nenhuma cidade encontrada com esse nome.</div>';
          dropdown.classList.add('show');
        } else {
          dropdown.innerHTML = results
            .map((item: any, idx: number) => {
              const subText = [item.region, item.country].filter(Boolean).join(' - ');
              return `
                <div class="city-dropdown-item" data-index="${idx}">
                  <div class="city-item-main">
                    <span class="city-item-name">${item.name}</span>
                    <span class="city-item-sub">${subText}</span>
                  </div>
                  <span class="city-item-coords">${Number(item.latitude).toFixed(2)}, ${Number(item.longitude).toFixed(2)}</span>
                </div>
              `;
            })
            .join('');
          dropdown.classList.add('show');

          // Eventos de clique nas opções
          dropdown.querySelectorAll('.city-dropdown-item').forEach((el) => {
            el.addEventListener('click', () => {
              const idx = parseInt(el.getAttribute('data-index') || '-1', 10);
              if (idx >= 0 && currentResults[idx]) {
                selectCityItem(currentResults[idx]);
              }
            });
          });
        }
      } catch (err) {
        dropdown.innerHTML = '<div class="city-dropdown-empty">Erro ao pesquisar cidades.</div>';
        dropdown.classList.add('show');
      } finally {
        if (spinner) spinner.classList.remove('active');
      }
    }, 350);
  });

  // Navegação por teclado no dropdown
  searchInput.addEventListener('keydown', (e) => {
    const items = dropdown.querySelectorAll('.city-dropdown-item');
    if (!dropdown.classList.contains('show') || items.length === 0) return;

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      focusedIndex = (focusedIndex + 1) % items.length;
      updateFocusedItem(items);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      focusedIndex = (focusedIndex - 1 + items.length) % items.length;
      updateFocusedItem(items);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (focusedIndex >= 0 && currentResults[focusedIndex]) {
        selectCityItem(currentResults[focusedIndex]);
      }
    } else if (e.key === 'Escape') {
      dropdown.classList.remove('show');
    }
  });

  function updateFocusedItem(items: NodeListOf<Element>) {
    items.forEach((item, idx) => {
      if (idx === focusedIndex) {
        item.classList.add('focused');
        item.scrollIntoView({ block: 'nearest' });
      } else {
        item.classList.remove('focused');
      }
    });
  }

  function selectCityItem(item: any) {
    const cityName = item.region ? `${item.name}, ${item.region}` : item.name;
    const provider = providerSelect ? providerSelect.value : 'open-meteo';

    updateSelectedCityDisplay(cityName, item.latitude, item.longitude, provider);
    searchInput.value = item.display_name || cityName;
    dropdown.classList.remove('show');

    showNotification(`Cidade selecionada: ${cityName}`, 'success');
    loadWeatherPreview();
  }

  // Fechar dropdown ao clicar fora
  document.addEventListener('click', (e) => {
    if (!searchInput.contains(e.target as Node) && !dropdown.contains(e.target as Node)) {
      dropdown.classList.remove('show');
    }
  });

  // Botão de Detecção Automática da Localização (GPS do Navegador + Fallback IP)
  btnDetect?.addEventListener('click', async () => {
    if (btnDetect.disabled) return;
    btnDetect.disabled = true;
    if (btnDetectText) btnDetectText.textContent = 'Detectando...';
    showNotification('Obtendo localização do computador...', 'success');

    const handleDetectedData = (data: any) => {
      const cityName = data.region ? `${data.name}, ${data.region}` : data.name;
      const provider = providerSelect ? providerSelect.value : 'open-meteo';

      updateSelectedCityDisplay(cityName, data.latitude, data.longitude, provider);
      searchInput.value = data.display_name || cityName;
      dropdown.classList.remove('show');
      showNotification(`📍 Localização detectada: ${cityName} (${data.country})!`, 'success');
      loadWeatherPreview();
    };

    const fallbackByIp = async () => {
      try {
        const res = await fetch(`${API_URL}/api/weather/cities/detect-ip`);
        if (!res.ok) throw new Error('Falha detecção IP');
        const data = await res.json();
        handleDetectedData(data);
      } catch (e) {
        showNotification('Não foi possível detectar a localização automaticamente.', 'error');
      } finally {
        btnDetect.disabled = false;
        if (btnDetectText) btnDetectText.textContent = 'Usar Localização Atual';
      }
    };

    if ('geolocation' in navigator) {
      navigator.geolocation.getCurrentPosition(
        async (position) => {
          try {
            const lat = position.coords.latitude;
            const lon = position.coords.longitude;
            const prov = providerSelect ? providerSelect.value : 'open-meteo';
            const res = await fetch(`${API_URL}/api/weather/cities/reverse?latitude=${lat}&longitude=${lon}&provider=${encodeURIComponent(prov)}`);
            if (res.ok) {
              const data = await res.json();
              handleDetectedData(data);
            } else {
              await fallbackByIp();
            }
          } catch (e) {
            await fallbackByIp();
          } finally {
            btnDetect.disabled = false;
            if (btnDetectText) btnDetectText.textContent = 'Usar Localização Atual';
          }
        },
        async (error) => {
          console.warn('Geolocalização do navegador indisponível ou negada, usando detecção por IP:', error.message);
          await fallbackByIp();
        },
        { timeout: 7000, enableHighAccuracy: true }
      );
    } else {
      await fallbackByIp();
    }
  });

  // Atalho da aba de Dispositivos (Pulseira) para ir à aba de Clima e focar o seletor
  btnGotoWeather?.addEventListener('click', () => {
    const integrationsBtn = document.querySelector('.nav-item[data-tab="integrations"]') as HTMLButtonElement;
    integrationsBtn?.click();
    setTimeout(() => {
      searchInput?.focus();
      searchInput?.select();
    }, 200);
  });

  // Atualizar badge do provedor caso o usuário mude o select
  providerSelect?.addEventListener('change', () => {
    const badgeEl = document.getElementById('selected-city-provider-badge');
    if (badgeEl) {
      const provNames: Record<string, string> = {
        'open-meteo': 'Open-Meteo',
        'openweathermap': 'OpenWeatherMap',
        'weatherapi': 'WeatherAPI'
      };
      badgeEl.textContent = provNames[providerSelect.value] || providerSelect.value;
    }
  });
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
    const ttlInput = document.getElementById('int-ttl') as HTMLInputElement;

    if (provInput) {
      provInput.value = config.weather_provider || 'open-meteo';
      syncCustomSelect(provInput);
    }
    if (tokenInput) tokenInput.value = config.weather_api_token || '';
    if (ttlInput) ttlInput.value = (config.cache_ttl_minutes ?? 30).toString();

    // Atualiza cidade e coordenadas nos campos e elementos visuais
    updateSelectedCityDisplay(
      config.weather_city || 'São Paulo',
      config.latitude ?? -23.5505,
      config.longitude ?? -46.6333,
      config.weather_provider || 'open-meteo'
    );
  } catch (err) {
    console.error('Erro ao carregar integrações:', err);
  }
}

// Mapeamento de ícones de clima para exibição visual
function getWeatherIcon(cond: string = ''): string {
  const c = cond.toLowerCase();
  if (c.includes('limpo') || c.includes('sol') || c.includes('ensolarado') || c.includes('clear')) return '☀️';
  if (c.includes('parcial') || c.includes('poucas')) return '⛅';
  if (c.includes('nublado') || c.includes('overcast') || c.includes('cloud')) return '☁️';
  if (c.includes('tempestade') || c.includes('trovo') || c.includes('thunder')) return '⛈️';
  if (c.includes('neve') || c.includes('snow')) return '❄️';
  if (c.includes('nevoeiro') || c.includes('fog') || c.includes('névoa')) return '🌫️';
  if (c.includes('chuva') || c.includes('pancada') || c.includes('rain') || c.includes('drizzle')) return '🌧️';
  return '🌤️';
}

interface WeatherLog {
  id: number;
  timestamp: string;
  city: string;
  temp: number;
  temp_min?: number;
  temp_max?: number;
  condition: string;
  humidity?: number;
  wind_speed?: number;
  weather_code?: number;
  provider: string;
  source: string;
}

// Carregar e Renderizar o Card de Clima do Dashboard (Hoje + Previsão de 7 dias)
async function loadDashboardWeather() {
  const iconEl = document.getElementById('dash-weather-icon');
  const tempEl = document.getElementById('dash-weather-temp');
  const hlEl = document.getElementById('dash-weather-hl');
  const condEl = document.getElementById('dash-weather-cond');
  const cityEl = document.getElementById('dash-weather-city');
  const humEl = document.getElementById('dash-weather-humidity');
  const windEl = document.getElementById('dash-weather-wind');
  const forecastGrid = document.getElementById('dashboard-forecast-days');

  if (!iconEl || !tempEl) return;

  try {
    const res = await fetch(`${API_URL}/api/weather/current`);
    if (!res.ok) return;
    const data = await res.json();

    const cur = data.current || data;
    const daily = data.daily_forecast || [];

    // Localidade
    if (cityEl) {
      const city = data.city || 'Localidade Padrão';
      cityEl.textContent = `📍 ${city}`;
    }

    // Clima de Hoje
    iconEl.textContent = getWeatherIcon(cur.condition);
    tempEl.textContent = `${cur.temp ?? '--'}`;
    if (condEl) condEl.textContent = cur.condition || 'Sem dados';

    if (hlEl) {
      if (daily.length > 0 && daily[0].temp_max !== undefined) {
        hlEl.textContent = `Máx: ${daily[0].temp_max}° / Mín: ${daily[0].temp_min}°`;
      } else {
        hlEl.textContent = `Máx: --° / Mín: --°`;
      }
    }

    if (humEl) humEl.textContent = `💧 ${cur.humidity || 50}%`;
    if (windEl) windEl.textContent = `💨 ${cur.wind_speed || 0} km/h`;

    // Atualizar defaults do formulário manual
    const inputTemp = document.getElementById('weather-temp') as HTMLInputElement | null;
    const inputCond = document.getElementById('weather-condition') as HTMLInputElement | null;
    if (inputTemp && cur.temp !== undefined) inputTemp.value = `${cur.temp}`;
    if (inputCond && cur.condition) inputCond.value = cur.condition;

    // Mini cards dos 7 dias
    if (forecastGrid && daily.length > 0) {
      forecastGrid.innerHTML = daily
        .map(
          (f: any) => `
        <div class="forecast-day-card">
          <div class="day-label">${f.day || f.date}</div>
          <div class="day-icon">${getWeatherIcon(f.condition)}</div>
          <div class="day-temp">
            <span class="temp-max">${f.temp_max}°</span>
            <span class="temp-sep">/</span>
            <span class="temp-min">${f.temp_min}°</span>
          </div>
          <div class="day-cond" title="${f.condition}">${f.condition}</div>
        </div>
      `
        )
        .join('');
    } else if (forecastGrid) {
      forecastGrid.innerHTML = '<div class="text-muted text-sm" style="grid-column: 1 / -1; text-align: center; padding: 8px 0;">Nenhuma previsão disponível</div>';
    }
  } catch (err) {
    console.error('Erro ao carregar clima do dashboard:', err);
    if (condEl) condEl.textContent = 'Erro ao consultar clima';
  }
}

// Carregar Prévia do Clima Estendido (Forecast de 7 Dias)
async function loadWeatherPreview() {
  const container = document.getElementById('weather-preview-content');
  if (!container) return;
  container.innerHTML = '<p class="text-muted">Consultando meteorologia estendida de 7 dias...</p>';

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
              <div class="day-icon">${getWeatherIcon(f.condition)}</div>
              <div class="day-temp">
                <span class="temp-max">${f.temp_max}°</span>
                <span class="temp-sep">/</span>
                <span class="temp-min">${f.temp_min}°</span>
              </div>
              <div class="day-cond" title="${f.condition}">${f.condition}</div>
            </div>
          `
            )
            .join('')}
        </div>
      `;
    }

    container.innerHTML = `
      <div class="d-flex align-center gap-3">
        <span style="font-size: 2.4rem;">${getWeatherIcon(cur.condition)}</span>
        <div>
          <div style="font-size: 1.3rem; font-weight: 700;">${cur.temp}°C - ${cur.condition}</div>
          <div class="text-muted text-sm">Umidade: ${cur.humidity || 50}% | Vento: ${cur.wind_speed || 0} km/h | Provedor: <strong>${data.provider || cur.provider || 'Open-Meteo'}</strong></div>
        </div>
      </div>
      ${forecastHtml}
    `;
  } catch (err) {
    container.innerHTML = '<p class="text-muted">Não foi possível carregar a previsão estendida do clima.</p>';
  }
}

// Carregar Histórico de Clima Gravado dos Dias Anteriores
async function loadWeatherHistory() {
  const tbody = document.getElementById('weather-history-table-body');
  if (!tbody) return;

  try {
    const res = await fetch(`${API_URL}/api/weather/history?limit=30`);
    if (!res.ok) return;
    const list: WeatherLog[] = await res.json();

    if (list.length === 0) {
      tbody.innerHTML = '<tr><td colspan="9" class="text-center text-muted py-3">Nenhum registro de clima gravado ainda. As consultas e sincronizações serão registradas aqui.</td></tr>';
      return;
    }

    tbody.innerHTML = list
      .map(
        (log) => `
        <tr>
          <td>${new Date(log.timestamp).toLocaleString('pt-BR')}</td>
          <td><strong>📍 ${log.city}</strong></td>
          <td><span style="font-weight: 700; color: #f8fafc;">${log.temp}°C</span></td>
          <td><span class="text-muted text-sm">${log.temp_min !== null && log.temp_min !== undefined ? log.temp_min : '--'}° / ${log.temp_max !== null && log.temp_max !== undefined ? log.temp_max : '--'}°</span></td>
          <td><span style="margin-right: 4px;">${getWeatherIcon(log.condition)}</span> ${log.condition}</td>
          <td>${log.humidity !== null && log.humidity !== undefined ? log.humidity + '%' : '--'}</td>
          <td>${log.wind_speed !== null && log.wind_speed !== undefined ? log.wind_speed + ' km/h' : '--'}</td>
          <td><span class="badge">${log.provider}</span></td>
          <td><span class="status-tag ${log.source.toLowerCase().includes('auto') ? 'scheduled' : 'manual'}">${log.source}</span></td>
        </tr>
      `
      )
      .join('');
  } catch (err) {
    tbody.innerHTML = '<tr><td colspan="9" class="text-center text-muted">Erro ao carregar histórico do clima.</td></tr>';
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
  const btnSyncNow = document.getElementById('btn-sync-now') as HTMLButtonElement;
  btnSyncNow?.addEventListener('click', async () => {
    if (btnSyncNow.disabled) return;
    btnSyncNow.disabled = true;
    btnSyncNow.innerHTML = '<span class="btn-icon">⏳</span> Sincronizando...';
    showNotification('Iniciando sincronização com a Mi Band...', 'success');

    try {
      const res = await fetch(`${API_URL}/api/sync`, { 
        method: 'POST', 
        headers: { 'Content-Type': 'application/json' }, 
        body: JSON.stringify({}) 
      });
      const data = await res.json();
      if (data.status === 'SUCCESS') {
        showNotification('🎉 Sincronização e envio de clima concluídos!', 'success');
        loadDashboard();
        loadDevicesList();
      } else {
        showNotification(data.message || 'Falha ao sincronizar com o relógio.', 'error');
      }
      loadHistory(); // Atualiza a aba histórico imediatamente
    } catch (e) {
      showNotification('Erro de comunicação com o servidor.', 'error');
    } finally {
      btnSyncNow.disabled = false;
      btnSyncNow.innerHTML = '<span class="btn-icon">🔄</span> Sincronizar Agora';
    }
  });

  // Localizar Pulseira (Vibrar) com proteção contra cliques repetidos
  const btnFindBand = document.getElementById('btn-find-band') as HTMLButtonElement;
  btnFindBand?.addEventListener('click', async () => {
    if (btnFindBand.disabled) return;
    btnFindBand.disabled = true;
    btnFindBand.innerHTML = '<span class="btn-icon">⏳</span> Enviando...';
    showNotification('Conectando à pulseira para disparar vibração...', 'success');

    try {
      const res = await fetch(`${API_URL}/api/vibrate`, { method: 'POST' });
      const data = await res.json();
      if (res.ok && data.success) {
        showNotification('🔔 Comando de vibração disparado na Mi Band 6!', 'success');
      } else {
        showNotification(data.message || 'Não foi possível vibrar. Verifique o sinal ou conexão.', 'error');
      }
    } catch (e) {
      showNotification('Erro ao conectar com o servidor.', 'error');
    } finally {
      btnFindBand.disabled = false;
      btnFindBand.innerHTML = '<span class="btn-icon">🔔</span> Localizar Pulseira';
    }
  });

  // Alternar Busca Automática (Pausar / Retomar)
  document.getElementById('btn-toggle-auto-scan')?.addEventListener('click', () => {
    const badge = document.getElementById('ble-radar-badge');
    const btnToggle = document.getElementById('btn-toggle-auto-scan');
    if (isAutoScanActive) {
      isAutoScanActive = false;
      stopAutoBleScan();
      if (badge) {
        badge.className = 'badge badge-radar paused';
        badge.innerHTML = '<span class="pulse-dot"></span> Busca Pausada';
      }
      if (btnToggle) btnToggle.textContent = '▶️ Retomar';
      showNotification('Busca automática pausada.', 'success');
    } else {
      isAutoScanActive = true;
      startAutoBleScan();
      if (badge) {
        badge.className = 'badge badge-radar active';
        badge.innerHTML = '<span class="pulse-dot"></span> Busca Automática Ativa';
      }
      if (btnToggle) btnToggle.textContent = '⏸️ Pausar';
      showNotification('Busca automática retomada!', 'success');
    }
  });

  // Salvar Dispositivo
  document.getElementById('form-config')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const mac = (document.getElementById('cfg-mac') as HTMLInputElement).value.trim();
    const name = (document.getElementById('cfg-name') as HTMLInputElement).value.trim();
    let auth = (document.getElementById('cfg-auth') as HTMLInputElement).value.trim();
    const intervalHours = parseInt((document.getElementById('cfg-interval-hours') as HTMLInputElement).value, 10) || 1;
    const intervals = currentScheduleTimes.join(', ');
    const autoWeather = (document.getElementById('cfg-auto-weather') as HTMLInputElement).checked;

    if (auth.startsWith('0x') || auth.startsWith('0X')) {
      auth = auth.substring(2);
    }

    if (!auth || auth.length !== 32) {
      showNotification(`Auth Key inválida (${auth.length} caracteres). Deve conter exatamente 32 caracteres hexadecimais.`, 'error');
      return;
    }

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
        const data = await res.json().catch(() => ({}));
        showNotification(data.detail || 'Falha ao salvar dispositivo.', 'error');
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
        updateSelectedCityDisplay(city, lat, lon, provider);
        loadWeatherPreview();
      } else {
        showNotification('Erro ao salvar integrações.', 'error');
      }
    } catch (err) {
      showNotification('Falha ao se comunicar com o servidor.', 'error');
    }
  });

  // Consultar Clima: primeiro consulta, atualiza os campos na tela e somente depois tenta sincronizar com a pulseira
  const btnConsult = (document.getElementById('btn-consult-weather') || document.getElementById('btn-refresh-weather-preview')) as HTMLButtonElement;
  btnConsult?.addEventListener('click', async () => {
    if (btnConsult.disabled) return;
    btnConsult.disabled = true;
    const originalHtml = btnConsult.innerHTML;
    btnConsult.innerHTML = '<span class="btn-icon">⏳</span> Consultando clima...';
    showNotification('Consultando previsão do tempo no serviço meteorológico...', 'success');

    try {
      // 1. Consulta o clima e atualiza os campos e a prévia de 7 dias
      await loadWeatherPreview();
      await loadWeatherHistory();

      // Atualiza também os campos da dashboard/formulário se estiverem no DOM
      const curData = await fetch(`${API_URL}/api/weather/current`).then((r) => (r.ok ? r.json() : null)).catch(() => null);
      if (curData && curData.current) {
        const cur = curData.current;
        const tempInput = document.getElementById('weather-temp') as HTMLInputElement;
        const condInput = document.getElementById('weather-condition') as HTMLInputElement;
        if (tempInput) tempInput.value = cur.temp;
        if (condInput) condInput.value = cur.condition;
      }

      // 2. Agora tenta sincronizar com a pulseira
      btnConsult.innerHTML = '<span class="btn-icon">⌚</span> Sincronizando com a pulseira...';
      showNotification('Previsão obtida! Conectando à Mi Band para sincronizar...', 'success');

      const syncRes = await fetch(`${API_URL}/api/weather`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ auto_fetch: true })
      });
      const syncData = await syncRes.json().catch(() => ({}));

      if (syncRes.ok && syncData.success) {
        showNotification(`🎉 Clima atualizado e sincronizado com a pulseira com sucesso (${syncData.temp}°C, ${syncData.condition})!`, 'success');
      } else {
        showNotification(syncData.message || 'Clima consultado e atualizado na tela, mas não foi possível conectar à pulseira via Bluetooth.', 'error');
      }

      // Atualiza o histórico para refletir o resultado da sincronização
      loadWeatherHistory();

    } catch (err) {
      showNotification('Erro ao consultar clima do servidor.', 'error');
    } finally {
      btnConsult.disabled = false;
      btnConsult.innerHTML = originalHtml;
    }
  });

  // Atualizar Histórico do Clima
  document.getElementById('btn-refresh-weather-history')?.addEventListener('click', () => {
    loadWeatherHistory();
    showNotification('Histórico do clima atualizado!', 'success');
  });

  // Consultar Clima no Dashboard e Sincronizar com a Pulseira
  document.getElementById('btn-dash-consult-weather')?.addEventListener('click', async () => {
    const btn = document.getElementById('btn-dash-consult-weather') as HTMLButtonElement | null;
    const oldHtml = btn ? btn.innerHTML : '';
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = '<span>⏳</span> Consultando...';
    }

    try {
      showNotification('Consultando clima atualizado...', 'info');
      await loadDashboardWeather();

      showNotification('Sincronizando previsão com a Mi Band 6...', 'info');
      const res = await fetch(`${API_URL}/api/weather`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ auto_fetch: true })
      });
      const data = await res.json();
      if (res.ok && data.success) {
        showNotification(`Clima (${data.temp}°C, ${data.condition}) sincronizado com sucesso na pulseira!`, 'success');
        loadWeatherHistory();
      } else {
        showNotification('Clima consultado na nuvem! (Pulseira não conectada para sincronização imediata)', 'info');
      }
    } catch (e) {
      showNotification('Erro ao sincronizar clima com o servidor.', 'error');
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = oldHtml;
      }
    }
  });

  // Alternar Visibilidade do Envio Manual de Clima
  document.getElementById('btn-dash-toggle-manual')?.addEventListener('click', () => {
    const row = document.getElementById('dash-manual-weather-row');
    if (row) {
      row.classList.toggle('hidden');
      if (!row.classList.contains('hidden')) {
        const inputTemp = document.getElementById('weather-temp') as HTMLInputElement | null;
        inputTemp?.focus();
      }
    }
  });

  // Enviar Clima Manual (Formulário do Dashboard)
  document.getElementById('form-weather')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const tempInput = document.getElementById('weather-temp') as HTMLInputElement | null;
    const condInput = document.getElementById('weather-condition') as HTMLInputElement | null;
    const temp = tempInput ? parseInt(tempInput.value, 10) : 24;
    const cond = condInput ? condInput.value : 'Ensolarado';

    try {
      const res = await fetch(`${API_URL}/api/weather`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ temp, condition: cond, auto_fetch: false })
      });
      if (res.ok) {
        showNotification(`Clima manual (${temp}°C, ${cond}) enviado para a Mi Band!`, 'success');
        loadWeatherHistory();
        loadDashboardWeather();
      } else {
        showNotification('Erro ao enviar clima manual.', 'error');
      }
    } catch (e) {
      showNotification('Falha ao se comunicar com a API.', 'error');
    }
  });
}

// Iniciar tudo ao carregar
window.addEventListener('DOMContentLoaded', () => {
  initTabs();
  setupEventListeners();
  initCitySelector();
  renderScheduleBadges();
  checkSystemStatus();
  loadDevicesList();
  loadIntegrations();
  loadWeatherHistory();
  loadDashboard();
  initTestTab(API_URL, showNotification);
  initBandSettingsTab(API_URL, showNotification);
  initCustomSelects();
});



