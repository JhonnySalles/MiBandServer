// Módulo da Aba de Testes & Laboratório da Mi Band 6

let API_BASE_URL = 'http://localhost:8190';
let notifyFn: (msg: string, type?: 'success' | 'error') => void = console.log;

interface LogEntry {
  ts: string;
  level: string;
  msg: string;
}

interface TestApiResponse<T = any> {
  success: boolean;
  duration_ms: number;
  data: T | null;
  error: string | null;
  logs: LogEntry[];
}

export function initTestTab(apiUrl: string, showToast: (msg: string, type?: 'success' | 'error') => void) {
  API_BASE_URL = apiUrl;
  notifyFn = showToast;

  setupConsoleActions();
  setupMetricCardsActions();
  setupWeatherActions();
  setupNotificationActions();
}

// -------------------------------------------------------------
// Gerenciamento do Console de Logs
// -------------------------------------------------------------
function appendLog(level: string, msg: string, ts?: string) {
  const box = document.getElementById('test-console-output');
  if (!box) return;

  const now = ts || new Date().toLocaleTimeString('pt-BR', { hour12: false }) + '.' + String(new Date().getMilliseconds()).padStart(3, '0');
  const line = document.createElement('div');
  line.className = `console-line ${level.toLowerCase()}`;

  const tsSpan = document.createElement('span');
  tsSpan.className = 'console-ts';
  tsSpan.textContent = now;

  const badgeSpan = document.createElement('span');
  badgeSpan.className = `console-badge ${level.toLowerCase()}`;
  badgeSpan.textContent = level;

  const msgSpan = document.createElement('span');
  msgSpan.className = 'console-msg';
  msgSpan.textContent = msg;

  line.appendChild(tsSpan);
  line.appendChild(badgeSpan);
  line.appendChild(msgSpan);

  box.appendChild(line);
  box.scrollTop = box.scrollHeight;
}

function appendBatchLogs(logs: LogEntry[]) {
  if (!logs || logs.length === 0) return;
  logs.forEach(l => appendLog(l.level, l.msg, l.ts));
}

function setConsoleStatus(statusText: string, isBusy: boolean = false) {
  const el = document.getElementById('test-console-status');
  if (!el) return;
  el.textContent = statusText;
  if (isBusy) {
    el.className = 'badge badge-radar active';
  } else {
    el.className = 'badge';
  }
}

function setupConsoleActions() {
  const btnClear = document.getElementById('btn-test-clear-logs');
  const btnCopy = document.getElementById('btn-test-copy-logs');
  const box = document.getElementById('test-console-output');

  if (btnClear && box) {
    btnClear.addEventListener('click', () => {
      box.innerHTML = '';
      appendLog('INFO', 'Console limpo pelo usuário.');
    });
  }

  if (btnCopy && box) {
    btnCopy.addEventListener('click', () => {
      const text = box.innerText;
      navigator.clipboard.writeText(text).then(() => {
        notifyFn('Logs copiados para a área de transferência!', 'success');
      }).catch(() => {
        notifyFn('Não foi possível copiar os logs.', 'error');
      });
    });
  }
}

// -------------------------------------------------------------
// Chamadas HTTP da API de Teste
// -------------------------------------------------------------
async function executeTestAction<T = any>(
  endpoint: string, 
  payload: any = {}, 
  actionLabel: string, 
  btnElement?: HTMLButtonElement | null
): Promise<TestApiResponse<T> | null> {
  if (btnElement) {
    btnElement.disabled = true;
    btnElement.classList.add('loading');
  }
  setConsoleStatus(`Executando ${actionLabel}...`, true);
  appendLog('INFO', `>>> Disparando comando: ${actionLabel}...`);

  try {
    const res = await fetch(`${API_BASE_URL}/api/test${endpoint}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    const result: TestApiResponse<T> = await res.json();
    appendBatchLogs(result.logs || []);

    if (result.success) {
      appendLog('OK', `✓ ${actionLabel} concluído em ${result.duration_ms}ms.`);
      notifyFn(`${actionLabel} realizado com sucesso! (${result.duration_ms}ms)`, 'success');
    } else {
      appendLog('ERROR', `✕ Falha em ${actionLabel}: ${result.error || 'Erro desconhecido'}`);
      notifyFn(`Erro: ${result.error || 'Falha na comunicação'}`, 'error');
    }

    return result;
  } catch (err: any) {
    appendLog('ERROR', `Exceção de rede ao comunicar com API: ${err.message}`);
    notifyFn(`Erro de comunicação: ${err.message}`, 'error');
    return null;
  } finally {
    if (btnElement) {
      btnElement.disabled = false;
      btnElement.classList.remove('loading');
    }
    setConsoleStatus('Pronto');
  }
}

// -------------------------------------------------------------
// Cards de Diagnóstico & Leituras
// -------------------------------------------------------------
function setupMetricCardsActions() {
  const btnReadAll = document.getElementById('btn-test-read-all') as HTMLButtonElement;
  const btnActivity = document.getElementById('btn-test-activity') as HTMLButtonElement;
  const btnBattery = document.getElementById('btn-test-battery') as HTMLButtonElement;
  const btnHeart = document.getElementById('btn-test-heart') as HTMLButtonElement;
  const btnTimeRead = document.getElementById('btn-test-time-read') as HTMLButtonElement;
  const btnTimeSync = document.getElementById('btn-test-time-sync') as HTMLButtonElement;
  const btnDeviceInfo = document.getElementById('btn-test-device-info') as HTMLButtonElement;
  const btnAlarms = document.getElementById('btn-test-alarms') as HTMLButtonElement;

  // 1. Sincronizar Tudo
  if (btnReadAll) {
    btnReadAll.addEventListener('click', async () => {
      const res = await executeTestAction<any>('/read-all', {}, 'Sincronizar Tudo', btnReadAll);
      if (res && res.success && res.data) {
        updateActivityUI(res.data.activity);
        updateBatteryUI(res.data.battery);
        updateDeviceInfoUI(res.data.device_info);
        updateTimeUI(res.data.time);
        updateAlarmsUI(res.data.alarms);
      }
    });
  }

  // 2. Atividade
  if (btnActivity) {
    btnActivity.addEventListener('click', async () => {
      const res = await executeTestAction<any>('/read/activity', {}, 'Leitura de Atividade', btnActivity);
      if (res && res.success && res.data) {
        updateActivityUI(res.data);
      }
    });
  }

  // 3. Bateria
  if (btnBattery) {
    btnBattery.addEventListener('click', async () => {
      const res = await executeTestAction<any>('/read/battery', {}, 'Leitura de Bateria', btnBattery);
      if (res && res.success && res.data) {
        updateBatteryUI(res.data);
      }
    });
  }

  // 4. Frequência Cardíaca (Sensor PPG)
  if (btnHeart) {
    btnHeart.addEventListener('click', async () => {
      const heartValEl = document.getElementById('test-val-heart');
      if (heartValEl) heartValEl.innerHTML = '<span class="pulse-dot"></span> Medindo...';
      const res = await executeTestAction<any>('/read/heart-rate', {}, 'Medição de Frequência Cardíaca', btnHeart);
      if (res && res.success && res.data && res.data.heart_rate) {
        if (heartValEl) heartValEl.innerHTML = `${res.data.heart_rate} <small>BPM</small>`;
        const timeEl = document.getElementById('test-time-heart');
        if (timeEl) timeEl.textContent = `Lido às ${new Date().toLocaleTimeString('pt-BR')}`;
      } else {
        if (heartValEl) heartValEl.innerHTML = '-- <small>BPM</small>';
      }
    });
  }

  // 5. Horário da Pulseira
  if (btnTimeRead) {
    btnTimeRead.addEventListener('click', async () => {
      const res = await executeTestAction<any>('/read/time', {}, 'Leitura de Horário', btnTimeRead);
      if (res && res.success && res.data) {
        updateTimeUI(res.data);
      }
    });
  }

  // 6. Sincronizar Relógio da Pulseira
  if (btnTimeSync) {
    btnTimeSync.addEventListener('click', async () => {
      const res = await executeTestAction<any>('/time/sync', {}, 'Ajuste do Relógio', btnTimeSync);
      if (res && res.success && res.data) {
        updateTimeUI(res.data.time);
      }
    });
  }

  // 7. Dados do Aparelho (DIS)
  if (btnDeviceInfo) {
    btnDeviceInfo.addEventListener('click', async () => {
      const res = await executeTestAction<any>('/read/device-info', {}, 'Leitura DIS', btnDeviceInfo);
      if (res && res.success && res.data) {
        updateDeviceInfoUI(res.data);
      }
    });
  }

  // 8. Alarmes
  if (btnAlarms) {
    btnAlarms.addEventListener('click', async () => {
      const res = await executeTestAction<any>('/read/alarms', {}, 'Consulta de Alarmes', btnAlarms);
      if (res && res.success && res.data) {
        updateAlarmsUI(res.data);
      }
    });
  }
}

function updateActivityUI(data: any) {
  if (!data) return;
  const stepsEl = document.getElementById('test-val-steps');
  const distEl = document.getElementById('test-val-distance');
  const calEl = document.getElementById('test-val-calories');
  const timeEl = document.getElementById('test-time-activity');

  if (stepsEl) stepsEl.textContent = (data.steps || 0).toLocaleString('pt-BR');
  if (distEl) distEl.textContent = `${(data.distance_meters || 0).toLocaleString('pt-BR')} m`;
  if (calEl) calEl.textContent = `${data.calories || 0} kcal`;
  if (timeEl) timeEl.textContent = `Atualizado às ${new Date().toLocaleTimeString('pt-BR')}`;
}

function updateBatteryUI(data: any) {
  if (!data) return;
  const batEl = document.getElementById('test-val-battery');
  const barEl = document.getElementById('test-battery-bar');
  const statusEl = document.getElementById('test-val-battery-status');
  const chargeEl = document.getElementById('test-val-battery-charge');
  const timeEl = document.getElementById('test-time-battery');

  const lvl = data.level !== null && data.level !== undefined ? data.level : '--';
  if (batEl) batEl.textContent = `${lvl}%`;
  if (barEl && data.level !== null) barEl.style.width = `${data.level}%`;
  if (statusEl) statusEl.textContent = data.status || '--';
  if (chargeEl) chargeEl.textContent = data.last_charge || 'N/A';
  if (timeEl) timeEl.textContent = `Lido às ${new Date().toLocaleTimeString('pt-BR')}`;
}

function updateDeviceInfoUI(data: any) {
  if (!data) return;
  const modelEl = document.getElementById('test-val-model');
  const fwEl = document.getElementById('test-val-fw');
  const hwEl = document.getElementById('test-val-hw');
  const serialEl = document.getElementById('test-val-serial');
  const timeEl = document.getElementById('test-time-device-info');

  if (modelEl) modelEl.textContent = data.model || 'Mi Smart Band 6';
  if (fwEl) fwEl.textContent = data.firmware_version || '--';
  if (hwEl) hwEl.textContent = data.hardware_version || '--';
  if (serialEl) serialEl.textContent = data.serial_number || '--';
  if (timeEl) timeEl.textContent = `Lido às ${new Date().toLocaleTimeString('pt-BR')}`;
}

function updateTimeUI(data: any) {
  if (!data) return;
  const bandEl = document.getElementById('test-val-band-time');
  const servEl = document.getElementById('test-val-server-time');
  const driftEl = document.getElementById('test-val-drift');
  const timeEl = document.getElementById('test-time-clock');

  if (bandEl) bandEl.textContent = data.band_time || '--';
  if (servEl) servEl.textContent = data.server_time || '--';
  if (driftEl) {
    const drift = data.drift_seconds || 0;
    driftEl.textContent = `${drift >= 0 ? '+' : ''}${drift}s`;
    if (Math.abs(drift) < 3) {
      driftEl.className = 'badge badge-pill text-success';
    } else {
      driftEl.className = 'badge badge-pill text-warning';
    }
  }
  if (timeEl) timeEl.textContent = `Verificado às ${new Date().toLocaleTimeString('pt-BR')}`;
}

function updateAlarmsUI(alarms: any[]) {
  const container = document.getElementById('test-alarms-list');
  const timeEl = document.getElementById('test-time-alarms');
  if (!container) return;

  if (!alarms || alarms.length === 0) {
    container.innerHTML = '<span class="text-muted text-xs">Nenhum alarme ativo configurado na pulseira.</span>';
  } else {
    container.innerHTML = alarms.map(a => `
      <div class="alarm-item-card ${a.enabled ? 'active' : 'inactive'}">
        <div class="alarm-info">
          <strong>${a.time}</strong>
          <span class="text-xs text-muted">Slot #${a.index}</span>
        </div>
        <span class="status-tag ${a.enabled ? 'success' : ''}">${a.enabled ? 'Ativo' : 'Desativado'}</span>
      </div>
    `).join('');
  }
  if (timeEl) timeEl.textContent = `Consultado às ${new Date().toLocaleTimeString('pt-BR')}`;
}

// -------------------------------------------------------------
// Seção de Previsão do Tempo
// -------------------------------------------------------------
interface DailyForecastItem {
  date?: string;
  day: string;
  temp_max: number;
  temp_min: number;
  condition: string;
  code?: number;
}

let activeForecastList: DailyForecastItem[] = [];
let activeCurrentWeather: any = null;

function setupWeatherActions() {
  const btnFetch = document.getElementById('btn-test-weather-fetch') as HTMLButtonElement;
  const btnSend = document.getElementById('btn-test-weather-send') as HTMLButtonElement;
  const cityInput = document.getElementById('test-weather-city') as HTMLInputElement;

  if (btnFetch) {
    btnFetch.addEventListener('click', async () => {
      btnFetch.disabled = true;
      appendLog('INFO', 'Consultando previsão estendida na API meteorológica...');
      try {
        const res = await fetch(`${API_BASE_URL}/api/test/weather/preview`);
        if (!res.ok) throw new Error('Falha na resposta da API');
        const data = await res.json();
        
        const cur = data.current || {};
        const daily = data.daily_forecast || [];
        activeCurrentWeather = cur;

        // Atualizar card de Hoje
        const todayTemp = document.getElementById('test-weather-today-temp') as HTMLInputElement;
        const todayCond = document.getElementById('test-weather-today-cond') as HTMLInputElement;
        if (todayTemp) todayTemp.value = String(cur.temp ?? 24);
        if (todayCond) todayCond.value = cur.condition ?? 'Ensolarado';

        // Renderizar cards dos próximos dias
        activeForecastList = daily;
        renderForecastEditorCards(daily);

        appendLog('OK', `Previsão obtida com sucesso: ${daily.length} dias futuros carregados.`);
        notifyFn('Previsão carregada! Você pode ajustar os valores antes de enviar.', 'success');
      } catch (e: any) {
        appendLog('ERROR', `Erro ao buscar previsão da internet: ${e.message}`);
        notifyFn('Erro ao buscar previsão meteorológica.', 'error');
      } finally {
        btnFetch.disabled = false;
      }
    });
  }

  if (btnSend) {
    btnSend.addEventListener('click', async () => {
      const city = cityInput ? cityInput.value.trim() : 'São Paulo';
      const todayTempEl = document.getElementById('test-weather-today-temp') as HTMLInputElement;
      const todayCondEl = document.getElementById('test-weather-today-cond') as HTMLInputElement;

      const condVal = todayCondEl?.value?.trim() || 'Ensolarado';
      // Se a condição for a mesma obtida da API, preserva o código. Se foi customizada, envia undefined para acionar motor semântico
      const curCode = (activeCurrentWeather && activeCurrentWeather.condition === condVal) 
        ? activeCurrentWeather.code 
        : undefined;

      const currentPayload = {
        temp: parseInt(todayTempEl?.value || '24', 10),
        condition: condVal,
        code: curCode
      };

      // Coletar dados editados dos dias futuros
      const dailyPayload: DailyForecastItem[] = [];
      const cards = document.querySelectorAll('.forecast-edit-card.future');
      cards.forEach((card, idx) => {
        const maxInput = card.querySelector('.input-temp-max') as HTMLInputElement;
        const minInput = card.querySelector('.input-temp-min') as HTMLInputElement;
        const condInput = card.querySelector('.input-cond') as HTMLInputElement;
        const labelSpan = card.querySelector('.day-badge') as HTMLElement;

        const dayCond = condInput?.value?.trim() || 'Ensolarado';
        const dayCode = (activeForecastList[idx] && activeForecastList[idx].condition === dayCond)
          ? activeForecastList[idx].code
          : undefined;

        dailyPayload.push({
          day: labelSpan ? labelSpan.textContent || `Dia ${idx + 1}` : `Dia ${idx + 1}`,
          temp_max: parseInt(maxInput?.value || '26', 10),
          temp_min: parseInt(minInput?.value || '18', 10),
          condition: dayCond,
          code: dayCode
        });
      });

      const body = {
        city,
        current: currentPayload,
        daily_forecast: dailyPayload
      };

      await executeTestAction('/weather/send', body, 'Envio de Previsão do Tempo', btnSend);
    });
  }
}

function renderForecastEditorCards(dailyList: DailyForecastItem[]) {
  const container = document.getElementById('test-weather-cards-container');
  if (!container) return;

  const todayCard = container.querySelector('.forecast-edit-card.today');
  container.innerHTML = '';
  if (todayCard) container.appendChild(todayCard);

  dailyList.forEach((item, idx) => {
    const card = document.createElement('div');
    card.className = 'forecast-edit-card future';
    card.innerHTML = `
      <span class="day-badge">${item.day || `Dia ${idx + 1}`}</span>
      <div class="form-row my-2">
        <div class="form-group flex-1">
          <label>Máx (°C)</label>
          <input type="number" class="input-temp-max" value="${item.temp_max ?? 26}" />
        </div>
        <div class="form-group flex-1">
          <label>Mín (°C)</label>
          <input type="number" class="input-temp-min" value="${item.temp_min ?? 18}" />
        </div>
      </div>
      <div class="form-group">
        <label>Condição</label>
        <input type="text" class="input-cond" list="weather-condition-presets" value="${item.condition || 'Ensolarado'}" />
      </div>
    `;
    container.appendChild(card);
  });
}

// -------------------------------------------------------------
// Seção de Notificação & Vibração
// -------------------------------------------------------------
function setupNotificationActions() {
  const formNotify = document.getElementById('form-test-notify') as HTMLFormElement;
  const btnVibrate = document.getElementById('btn-test-trigger-vibrate') as HTMLButtonElement;

  if (formNotify) {
    formNotify.addEventListener('submit', async (e) => {
      e.preventDefault();
      const catEl = document.getElementById('test-notify-category') as HTMLSelectElement;
      const titleEl = document.getElementById('test-notify-title') as HTMLInputElement;
      const textEl = document.getElementById('test-notify-text') as HTMLInputElement;
      const submitBtn = formNotify.querySelector('button[type="submit"]') as HTMLButtonElement;

      const body = {
        category: parseInt(catEl?.value || '3', 10),
        title: titleEl?.value.trim() || 'MiBand Hub',
        text: textEl?.value.trim() || 'Teste'
      };

      await executeTestAction('/notify', body, 'Disparo de Notificação', submitBtn);
    });
  }

  if (btnVibrate) {
    btnVibrate.addEventListener('click', async () => {
      const countEl = document.getElementById('test-vibrate-count') as HTMLSelectElement;
      const textEl = document.getElementById('test-vibrate-text') as HTMLInputElement;

      const body = {
        count: parseInt(countEl?.value || '2', 10),
        text: textEl?.value.trim() || 'Localizar MiBand'
      };

      await executeTestAction('/vibrate', body, 'Disparo de Vibração', btnVibrate);
    });
  }
}
