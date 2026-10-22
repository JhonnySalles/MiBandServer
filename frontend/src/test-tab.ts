// Módulo da Aba de Testes & Laboratório da Mi Band 6

let API_BASE_URL = 'http://localhost:8190';
let notifyFn: (msg: string, type?: 'success' | 'error' | 'info') => void = console.log;

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

export function initTestTab(apiUrl: string, showToast: (msg: string, type?: 'success' | 'error' | 'info') => void) {
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
// Indicadores de Progresso Visuais ao Lado dos Botões
// -------------------------------------------------------------
function setButtonProgress(
  indicatorId: string, 
  state: 'idle' | 'running' | 'success' | 'error', 
  text?: string
) {
  const el = document.getElementById(indicatorId);
  if (!el) return;

  if (state === 'idle') {
    el.className = 'test-progress-inline';
    el.innerHTML = '';
  } else if (state === 'running') {
    el.className = 'test-progress-inline running';
    el.innerHTML = `<span class="test-spinner"></span> <span>${text || 'Executando...'}</span>`;
  } else if (state === 'success') {
    el.className = 'test-progress-inline success';
    el.innerHTML = `<span>✓</span> <span>${text || 'Concluído'}</span>`;
    setTimeout(() => {
      if (el.classList.contains('success')) {
        setButtonProgress(indicatorId, 'idle');
      }
    }, 4500);
  } else if (state === 'error') {
    el.className = 'test-progress-inline error';
    el.innerHTML = `<span>✕</span> <span>${text || 'Falha'}</span>`;
    setTimeout(() => {
      if (el.classList.contains('error')) {
        setButtonProgress(indicatorId, 'idle');
      }
    }, 5500);
  }
}

function setReadAllProgress(
  percent: number, 
  stepText: string, 
  isDone: boolean = false, 
  isError: boolean = false
) {
  const wrap = document.getElementById('progress-test-read-all');
  if (!wrap) return;

  if (isDone) {
    wrap.innerHTML = `
      <div class="test-progress-inline success" style="align-self: flex-start;">
        <span>✓</span> <span>${stepText || 'Sincronização concluída!'}</span>
      </div>
    `;
    setTimeout(() => {
      wrap.innerHTML = '';
    }, 5000);
    return;
  }

  if (isError) {
    wrap.innerHTML = `
      <div class="test-progress-inline error" style="align-self: flex-start;">
        <span>✕</span> <span>${stepText || 'Erro na sincronização'}</span>
      </div>
    `;
    setTimeout(() => {
      wrap.innerHTML = '';
    }, 6000);
    return;
  }

  wrap.innerHTML = `
    <div class="test-progress-bar-label">
      <span class="step-text">${stepText}</span>
      <span class="percent-text">${percent}%</span>
    </div>
    <div class="test-progress-bar-container">
      <div class="test-progress-bar-fill" style="width: ${percent}%;"></div>
    </div>
  `;
}

// -------------------------------------------------------------
// Chamadas HTTP / SSE da API de Teste com Callback em Tempo Real
// -------------------------------------------------------------
async function executeStreamTestAction<T = any>(
  action: string, 
  payload: any = {}, 
  actionLabel: string, 
  btnElement?: HTMLButtonElement | null,
  indicatorId?: string,
  onStepDone?: (step: string, data: any) => void
): Promise<TestApiResponse<T> | null> {
  if (btnElement) {
    btnElement.disabled = true;
    btnElement.classList.add('loading');
  }

  if (indicatorId) {
    setButtonProgress(indicatorId, 'running', 'Iniciando...');
  }
  if (action === 'read_all') {
    setReadAllProgress(5, 'Iniciando sincronização...');
  }

  setConsoleStatus(`Executando ${actionLabel}...`, true);
  appendLog('INFO', `>>> Disparando comando: ${actionLabel}...`);

  const requestBody = {
    action,
    ...payload
  };

  try {
    const res = await fetch(`${API_BASE_URL}/api/test/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(requestBody)
    });

    if (!res.ok) {
      throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    }

    const reader = res.body?.getReader();
    if (!reader) {
      throw new Error('Streaming não suportado pelo navegador.');
    }

    const decoder = new TextDecoder('utf-8');
    let buffer = '';
    let finalResult: TestApiResponse<T> | null = null;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n\n');
      buffer = lines.pop() || '';

      for (const block of lines) {
        const trimmed = block.trim();
        if (!trimmed.startsWith('data:')) continue;
        const jsonStr = trimmed.replace(/^data:\s*/, '');
        try {
          const ev = JSON.parse(jsonStr);

          if (ev.type === 'log') {
            appendLog(ev.level, ev.msg, ev.ts);
          } else if (ev.type === 'progress') {
            if (indicatorId) {
              setButtonProgress(indicatorId, 'running', ev.message || 'Executando...');
            }
            if (action === 'read_all') {
              setReadAllProgress(ev.percent || 0, ev.message || 'Processando...');
            }
          } else if (ev.type === 'step_done') {
            if (onStepDone) {
              onStepDone(ev.step, ev.data);
            }
            if (action === 'read_all') {
              setReadAllProgress(ev.percent || 0, ev.message || 'Etapa concluída');
            }
          } else if (ev.type === 'complete') {
            finalResult = ev;
          }
        } catch (parseErr) {
          console.error('Erro ao analisar mensagem SSE:', parseErr, jsonStr);
        }
      }
    }

    if (finalResult && finalResult.success) {
      const durationStr = `${finalResult.duration_ms}ms`;
      if (indicatorId) {
        setButtonProgress(indicatorId, 'success', `Concluído (${durationStr})`);
      }
      if (action === 'read_all') {
        setReadAllProgress(100, `Sincronização concluída em ${durationStr}!`, true);
      }
      appendLog('OK', `✓ ${actionLabel} concluído em ${durationStr}.`);
      notifyFn(`${actionLabel} realizado com sucesso! (${durationStr})`, 'success');
      return finalResult;
    } else {
      const errMsg = finalResult?.error || 'Falha na execução';
      const shortErr = errMsg.length > 24 ? errMsg.substring(0, 22) + '...' : errMsg;
      if (indicatorId) {
        setButtonProgress(indicatorId, 'error', shortErr);
      }
      if (action === 'read_all') {
        setReadAllProgress(0, shortErr, false, true);
      }
      appendLog('ERROR', `✕ Falha em ${actionLabel}: ${errMsg}`);
      notifyFn(`Erro: ${errMsg}`, 'error');
      return finalResult;
    }

  } catch (err: any) {
    const errText = err.message || 'Erro de rede';
    if (indicatorId) {
      setButtonProgress(indicatorId, 'error', 'Erro de conexão');
    }
    if (action === 'read_all') {
      setReadAllProgress(0, errText, false, true);
    }
    appendLog('ERROR', `Exceção de rede ao comunicar com API: ${errText}`);
    notifyFn(`Erro de comunicação: ${errText}`, 'error');
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
  const btnReadAll = document.getElementById('btn-test-read-all') as HTMLButtonElement | null;
  const btnActivity = document.getElementById('btn-test-activity') as HTMLButtonElement | null;
  const btnBattery = document.getElementById('btn-test-battery') as HTMLButtonElement | null;
  const btnHeart = document.getElementById('btn-test-heart') as HTMLButtonElement | null;
  const btnTimeRead = document.getElementById('btn-test-time-read') as HTMLButtonElement | null;
  const btnTimeSync = document.getElementById('btn-test-time-sync') as HTMLButtonElement | null;
  const btnDeviceInfo = document.getElementById('btn-test-device-info') as HTMLButtonElement | null;
  const btnAlarms = document.getElementById('btn-test-alarms') as HTMLButtonElement | null;

  // 1. Sincronizar Tudo
  if (btnReadAll) {
    btnReadAll.addEventListener('click', async () => {
      // Inicia indicadores nos cards individuais para feedback sincronizado
      setButtonProgress('progress-test-activity', 'running', 'Aguardando...');
      setButtonProgress('progress-test-battery', 'running', 'Aguardando...');
      setButtonProgress('progress-test-device-info', 'running', 'Aguardando...');
      setButtonProgress('progress-test-time', 'running', 'Aguardando...');
      setButtonProgress('progress-test-alarms', 'running', 'Aguardando...');

      const res = await executeStreamTestAction<any>(
        'read_all', 
        {}, 
        'Sincronizar Tudo', 
        btnReadAll,
        undefined,
        (step, data) => {
          // Callback em tempo real: atualiza imediatamente cada card assim que recebido
          if (step === 'activity') {
            updateActivityUI(data);
            setButtonProgress('progress-test-activity', 'success', 'Lido');
          } else if (step === 'battery') {
            updateBatteryUI(data);
            setButtonProgress('progress-test-battery', 'success', 'Lido');
          } else if (step === 'device_info') {
            updateDeviceInfoUI(data);
            setButtonProgress('progress-test-device-info', 'success', 'Lido');
          } else if (step === 'time') {
            updateTimeUI(data);
            setButtonProgress('progress-test-time', 'success', 'Verificado');
          } else if (step === 'alarms') {
            updateAlarmsUI(data);
            setButtonProgress('progress-test-alarms', 'success', 'Lido');
          }
        }
      );

      if (res && res.success && res.data) {
        updateActivityUI(res.data.activity);
        updateBatteryUI(res.data.battery);
        updateDeviceInfoUI(res.data.device_info);
        updateTimeUI(res.data.time);
        updateAlarmsUI(res.data.alarms);
      } else if (!res || !res.success) {
        setButtonProgress('progress-test-activity', 'error', 'Interrompido');
        setButtonProgress('progress-test-battery', 'error', 'Interrompido');
        setButtonProgress('progress-test-device-info', 'error', 'Interrompido');
        setButtonProgress('progress-test-time', 'error', 'Interrompido');
        setButtonProgress('progress-test-alarms', 'error', 'Interrompido');
      }
    });
  }

  // 2. Atividade
  if (btnActivity) {
    btnActivity.addEventListener('click', async () => {
      const res = await executeStreamTestAction<any>(
        'activity', 
        {}, 
        'Leitura de Atividade', 
        btnActivity,
        'progress-test-activity'
      );
      if (res && res.success && res.data) {
        updateActivityUI(res.data);
      }
    });
  }

  // 3. Bateria
  if (btnBattery) {
    btnBattery.addEventListener('click', async () => {
      const res = await executeStreamTestAction<any>(
        'battery', 
        {}, 
        'Leitura de Bateria', 
        btnBattery,
        'progress-test-battery'
      );
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
      
      const res = await executeStreamTestAction<any>(
        'heart_rate', 
        {}, 
        'Medição de Frequência Cardíaca', 
        btnHeart,
        'progress-test-heart'
      );
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
      const res = await executeStreamTestAction<any>(
        'time_read', 
        {}, 
        'Leitura de Horário', 
        btnTimeRead,
        'progress-test-time'
      );
      if (res && res.success && res.data) {
        updateTimeUI(res.data);
      }
    });
  }

  // 6. Sincronizar Relógio da Pulseira
  if (btnTimeSync) {
    btnTimeSync.addEventListener('click', async () => {
      const res = await executeStreamTestAction<any>(
        'time_sync', 
        {}, 
        'Ajuste do Relógio', 
        btnTimeSync,
        'progress-test-time'
      );
      if (res && res.success && res.data) {
        updateTimeUI(res.data.time);
      }
    });
  }

  // 7. Dados do Aparelho (DIS)
  if (btnDeviceInfo) {
    btnDeviceInfo.addEventListener('click', async () => {
      const res = await executeStreamTestAction<any>(
        'device_info', 
        {}, 
        'Leitura DIS', 
        btnDeviceInfo,
        'progress-test-device-info'
      );
      if (res && res.success && res.data) {
        updateDeviceInfoUI(res.data);
      }
    });
  }

  // 8. Alarmes
  if (btnAlarms) {
    btnAlarms.addEventListener('click', async () => {
      const res = await executeStreamTestAction<any>(
        'alarms', 
        {}, 
        'Consulta de Alarmes', 
        btnAlarms,
        'progress-test-alarms'
      );
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
  const btnFetch = document.getElementById('btn-test-weather-fetch') as HTMLButtonElement | null;
  const btnSend = document.getElementById('btn-test-weather-send') as HTMLButtonElement | null;
  const cityInput = document.getElementById('test-weather-city') as HTMLInputElement | null;

  if (btnFetch) {
    btnFetch.addEventListener('click', async () => {
      const city = cityInput ? cityInput.value.trim() : 'São Paulo';
      const res = await executeStreamTestAction<any>(
        'weather_preview',
        { city },
        'Consulta de Previsão',
        btnFetch,
        'progress-test-weather'
      );

      if (res && res.success && res.data) {
        const cur = res.data.current || {};
        const daily = res.data.daily_forecast || [];
        activeCurrentWeather = cur;

        const todayTemp = document.getElementById('test-weather-today-temp') as HTMLInputElement | null;
        const todayCond = document.getElementById('test-weather-today-cond') as HTMLInputElement | null;
        if (todayTemp) todayTemp.value = String(cur.temp ?? 24);
        if (todayCond) todayCond.value = cur.condition ?? 'Ensolarado';

        activeForecastList = daily;
        renderForecastEditorCards(daily);
      }
    });
  }

  if (btnSend) {
    btnSend.addEventListener('click', async () => {
      const city = cityInput ? cityInput.value.trim() : 'São Paulo';
      const todayTempEl = document.getElementById('test-weather-today-temp') as HTMLInputElement | null;
      const todayCondEl = document.getElementById('test-weather-today-cond') as HTMLInputElement | null;

      const condVal = todayCondEl?.value?.trim() || 'Ensolarado';
      const curCode = (activeCurrentWeather && activeCurrentWeather.condition === condVal) 
        ? activeCurrentWeather.code 
        : undefined;

      const currentPayload = {
        temp: parseInt(todayTempEl?.value || '24', 10),
        condition: condVal,
        code: curCode
      };

      const dailyPayload: DailyForecastItem[] = [];
      const cards = document.querySelectorAll('.forecast-edit-card.future');
      cards.forEach((card, idx) => {
        const maxInput = card.querySelector('.input-temp-max') as HTMLInputElement | null;
        const minInput = card.querySelector('.input-temp-min') as HTMLInputElement | null;
        const condInput = card.querySelector('.input-cond') as HTMLInputElement | null;
        const labelSpan = card.querySelector('.day-badge') as HTMLElement | null;

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

      await executeStreamTestAction(
        'weather_send', 
        body, 
        'Envio de Previsão do Tempo', 
        btnSend,
        'progress-test-weather'
      );
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
  const formNotify = document.getElementById('form-test-notify') as HTMLFormElement | null;
  const btnVibrate = document.getElementById('btn-test-trigger-vibrate') as HTMLButtonElement | null;

  if (formNotify) {
    formNotify.addEventListener('submit', async (e) => {
      e.preventDefault();
      const catEl = document.getElementById('test-notify-category') as HTMLSelectElement | null;
      const titleEl = document.getElementById('test-notify-title') as HTMLInputElement | null;
      const textEl = document.getElementById('test-notify-text') as HTMLInputElement | null;
      const submitBtn = formNotify.querySelector('button[type="submit"]') as HTMLButtonElement | null;

      const body = {
        category: parseInt(catEl?.value || '3', 10),
        title: titleEl?.value.trim() || 'MiBand Hub',
        text: textEl?.value.trim() || 'Teste'
      };

      await executeStreamTestAction(
        'notify', 
        body, 
        'Disparo de Notificação', 
        submitBtn,
        'progress-test-notify'
      );
    });
  }

  if (btnVibrate) {
    btnVibrate.addEventListener('click', async () => {
      const countEl = document.getElementById('test-vibrate-count') as HTMLSelectElement | null;
      const textEl = document.getElementById('test-vibrate-text') as HTMLInputElement | null;

      const body = {
        count: parseInt(countEl?.value || '2', 10),
        text: textEl?.value.trim() || 'Localizar MiBand'
      };

      await executeStreamTestAction(
        'vibrate', 
        body, 
        'Disparo de Vibração', 
        btnVibrate,
        'progress-test-vibrate'
      );
    });
  }
}
