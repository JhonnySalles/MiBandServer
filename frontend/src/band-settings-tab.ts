// Módulo da Aba de Configurações da Pulseira Mi Smart Band 6
import { syncCustomSelect } from './custom-select';

let API_BASE_URL = 'http://localhost:8190';
let notifyFn: (msg: string, type?: 'success' | 'error' | 'info') => void = console.log;

export interface BandReminder {
  id?: string;
  title: string;
  datetime: string;
}

export interface BandAlarm {
  id?: number;
  hours: number;
  minutes: number;
  enabled: boolean;
  snooze: boolean;
  days: number[]; // 0=Dom, 1=Seg, 2=Ter, 3=Qua, 4=Qui, 5=Sex, 6=Sáb
}

export interface BandWorldClock {
  city: string;
  timezone: number; // UTC offset em horas (ex: -3, 0, 9)
}

export interface BandSettingsData {
  device_mac: string;
  event_reminders: BandReminder[];
  alarms: BandAlarm[];
  world_clocks: BandWorldClock[];
  lift_wrist_mode: 'off' | 'all_day' | 'scheduled';
  lift_wrist_start: string;
  lift_wrist_end: string;
  lift_wrist_speed: 'normal' | 'fast';
  night_mode: 'off' | 'sunset' | 'scheduled';
  night_mode_start: string;
  night_mode_end: string;
  dnd_mode: 'off' | 'smart' | 'all_day' | 'scheduled';
  wear_location: 'left' | 'right';
  language: string;
}

let settingsState: BandSettingsData = {
  device_mac: '',
  event_reminders: [],
  alarms: [],
  world_clocks: [],
  lift_wrist_mode: 'all_day',
  lift_wrist_start: '07:00',
  lift_wrist_end: '22:00',
  lift_wrist_speed: 'normal',
  night_mode: 'sunset',
  night_mode_start: '22:00',
  night_mode_end: '07:00',
  dnd_mode: 'smart',
  wear_location: 'left',
  language: 'pt_BR'
};

let worldClockInterval: any = null;

export function initBandSettingsTab(apiUrl: string, showToast: (msg: string, type?: 'success' | 'error' | 'info') => void) {
  API_BASE_URL = apiUrl;
  notifyFn = showToast;

  setupTopBarActions();
  setupRemindersSection();
  setupAlarmsSection();
  setupWorldClocksSection();
  setupLiftWristSection();
  setupNightModeSection();
  setupWearLocationSection();
  setupLanguageSection();

  // Iniciar relógio mundial atualizando a cada segundo
  if (worldClockInterval) clearInterval(worldClockInterval);
  worldClockInterval = setInterval(() => {
    updateWorldClocksTimeDisplay();
  }, 1000);

  // Primeira carga
  loadBandSettings();
}

// -------------------------------------------------------------
// Indicador de Progresso Inline
// -------------------------------------------------------------
function setProgress(indicatorId: string, state: 'idle' | 'running' | 'success' | 'error', text?: string) {
  const el = document.getElementById(indicatorId);
  if (!el) return;

  if (state === 'idle') {
    el.className = 'test-progress-inline';
    el.innerHTML = '';
  } else if (state === 'running') {
    el.className = 'test-progress-inline running';
    el.innerHTML = `<span class="test-spinner"></span> <span>${text || 'Sincronizando...'}</span>`;
  } else if (state === 'success') {
    el.className = 'test-progress-inline success';
    el.innerHTML = `<span>✓</span> <span>${text || 'Sincronizado!'}</span>`;
    setTimeout(() => {
      if (el.classList.contains('success')) {
        setProgress(indicatorId, 'idle');
      }
    }, 4500);
  } else if (state === 'error') {
    el.className = 'test-progress-inline error';
    el.innerHTML = `<span>✕</span> <span>${text || 'Falha'}</span>`;
    setTimeout(() => {
      if (el.classList.contains('error')) {
        setProgress(indicatorId, 'idle');
      }
    }, 5500);
  }
}

// -------------------------------------------------------------
// Carregar Configurações da API
// -------------------------------------------------------------
export async function loadBandSettings() {
  try {
    const res = await fetch(`${API_BASE_URL}/api/band/settings`);
    if (!res.ok) throw new Error('Falha ao obter configurações da pulseira');
    const data: BandSettingsData = await res.json();
    settingsState = data;

    // Atualizar Badge do dispositivo
    const badge = document.getElementById('band-settings-device-badge');
    if (badge && data.device_mac) {
      badge.textContent = `Pulseira: ${data.device_mac}`;
    }

    renderReminders();
    renderAlarms();
    renderWorldClocks();
    updateSystemControlsFromState();
  } catch (err: any) {
    console.error('Erro ao carregar configurações da pulseira:', err);
  }
}

// -------------------------------------------------------------
// Top Bar Actions (Salvar Tudo & Ler da Pulseira)
// -------------------------------------------------------------
function setupTopBarActions() {
  const btnRead = document.getElementById('btn-band-read');
  const btnSaveSync = document.getElementById('btn-band-save-sync');

  btnRead?.addEventListener('click', async () => {
    setProgress('progress-band-settings-global', 'running', 'Lendo da pulseira...');
    try {
      const res = await fetch(`${API_BASE_URL}/api/band/settings/read`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scope: 'alarms' })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Falha ao ler dados da pulseira');

      setProgress('progress-band-settings-global', 'success', 'Alarmes lidos!');
      notifyFn(data.message || 'Alarmes sincronizados com sucesso!', 'success');
      if (data.settings) {
        settingsState = data.settings;
        renderAlarms();
      }
    } catch (err: any) {
      setProgress('progress-band-settings-global', 'error', 'Erro');
      notifyFn(err.message, 'error');
    }
  });

  btnSaveSync?.addEventListener('click', async () => {
    setProgress('progress-band-settings-global', 'running', 'Sincronizando tudo...');
    try {
      // 1. Salvar no banco
      collectCurrentFormToState();
      const putRes = await fetch(`${API_BASE_URL}/api/band/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settingsState)
      });
      const putData = await putRes.json();
      if (!putRes.ok) throw new Error(putData.detail || 'Falha ao salvar no banco');

      // 2. Enviar tudo via BLE para a pulseira
      const syncRes = await fetch(`${API_BASE_URL}/api/band/settings/sync`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scope: 'all' })
      });
      const syncData = await syncRes.json();
      if (!syncRes.ok) throw new Error(syncData.detail || 'Falha ao sincronizar via BLE');

      setProgress('progress-band-settings-global', 'success', 'Pulseira atualizada!');
      notifyFn('Todas as configurações foram enviadas para a Mi Smart Band 6!', 'success');
    } catch (err: any) {
      setProgress('progress-band-settings-global', 'error', 'Erro');
      notifyFn(err.message, 'error');
    }
  });
}

// -------------------------------------------------------------
// Salvar alterações e sincronizar escopo individual
// -------------------------------------------------------------
async function saveAndSyncScope(scope: string, progressId: string, successMsg: string) {
  setProgress(progressId, 'running', 'Enviando...');
  try {
    collectCurrentFormToState();
    
    // 1. Salvar banco
    const putRes = await fetch(`${API_BASE_URL}/api/band/settings`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settingsState)
    });
    if (!putRes.ok) {
      const err = await putRes.json();
      throw new Error(err.detail || 'Erro ao persistir configuração');
    }

    // 2. Sincronizar BLE
    const syncRes = await fetch(`${API_BASE_URL}/api/band/settings/sync`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scope })
    });
    const syncData = await syncRes.json();
    if (!syncRes.ok) throw new Error(syncData.detail || 'Erro ao sincronizar com pulseira');

    setProgress(progressId, 'success', 'Aplicado!');
    notifyFn(successMsg, 'success');
  } catch (err: any) {
    setProgress(progressId, 'error', 'Falha');
    notifyFn(err.message, 'error');
  }
}

// -------------------------------------------------------------
// 1. Lembretes de Eventos
// -------------------------------------------------------------
function setupRemindersSection() {
  const btnAdd = document.getElementById('btn-add-reminder');
  const btnSync = document.getElementById('btn-sync-reminders');
  const inputTitle = document.getElementById('input-reminder-title') as HTMLInputElement;
  const inputDatetime = document.getElementById('input-reminder-datetime') as HTMLInputElement;

  // Set default datetime to tomorrow 09:00
  if (inputDatetime) {
    const tmr = new Date();
    tmr.setDate(tmr.getDate() + 1);
    tmr.setHours(9, 0, 0, 0);
    const pad = (n: number) => String(n).padStart(2, '0');
    inputDatetime.value = `${tmr.getFullYear()}-${pad(tmr.getMonth() + 1)}-${pad(tmr.getDate())}T${pad(tmr.getHours())}:${pad(tmr.getMinutes())}`;
  }

  btnAdd?.addEventListener('click', () => {
    const title = inputTitle?.value?.trim();
    const datetime = inputDatetime?.value;

    if (!title) {
      notifyFn('Digite um título para o lembrete.', 'info');
      inputTitle?.focus();
      return;
    }
    if (!datetime) {
      notifyFn('Selecione uma data e horário válidos.', 'info');
      inputDatetime?.focus();
      return;
    }

    if (!Array.isArray(settingsState.event_reminders)) {
      settingsState.event_reminders = [];
    }

    settingsState.event_reminders.push({
      id: 'rem_' + Date.now(),
      title,
      datetime
    });

    inputTitle.value = '';
    renderReminders();
    notifyFn('Lembrete adicionado! Clique em "Sincronizar Lembretes" para enviar à pulseira.', 'info');
  });

  btnSync?.addEventListener('click', () => {
    saveAndSyncScope('reminders', 'progress-sync-reminders', 'Lembretes sincronizados com a Mi Band!');
  });
}

function renderReminders() {
  const container = document.getElementById('band-reminders-list');
  const badgeCount = document.getElementById('badge-reminders-count');
  if (!container) return;

  const list = settingsState.event_reminders || [];
  if (badgeCount) {
    badgeCount.textContent = `${list.length} lembrete${list.length !== 1 ? 's' : ''}`;
  }

  if (list.length === 0) {
    container.innerHTML = '<div class="band-empty-state">Nenhum lembrete cadastrado. Adicione um acima.</div>';
    return;
  }

  container.innerHTML = '';
  list.forEach((rem, idx) => {
    const d = new Date(rem.datetime);
    const dateFormatted = !isNaN(d.getTime()) 
      ? d.toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
      : rem.datetime;

    const item = document.createElement('div');
    item.className = 'reminder-item-card';
    item.innerHTML = `
      <div>
        <div class="reminder-item-title">${escapeHtml(rem.title)}</div>
        <div class="reminder-item-date">
          <span>📅</span> <span>${dateFormatted}</span>
        </div>
      </div>
      <button type="button" class="btn-icon-delete" title="Excluir lembrete">✕</button>
    `;

    const btnDel = item.querySelector('.btn-icon-delete');
    btnDel?.addEventListener('click', () => {
      settingsState.event_reminders.splice(idx, 1);
      renderReminders();
    });

    container.appendChild(item);
  });
}

// -------------------------------------------------------------
// 2. Alarmes da Pulseira
// -------------------------------------------------------------
function setupAlarmsSection() {
  const btnAdd = document.getElementById('btn-add-alarm');
  const btnSync = document.getElementById('btn-sync-alarms');
  const inputTime = document.getElementById('input-alarm-time') as HTMLInputElement;
  const inputSnooze = document.getElementById('input-alarm-snooze') as HTMLInputElement;
  const dayPills = document.querySelectorAll('#alarm-days-group .day-pill');

  dayPills.forEach((pill) => {
    pill.addEventListener('click', () => {
      pill.classList.toggle('active');
    });
  });

  btnAdd?.addEventListener('click', () => {
    const timeVal = inputTime?.value;
    if (!timeVal) {
      notifyFn('Selecione um horário para o alarme.', 'info');
      return;
    }

    if (!Array.isArray(settingsState.alarms)) {
      settingsState.alarms = [];
    }

    if (settingsState.alarms.length >= 10) {
      notifyFn('A Mi Band suporta no máximo 10 alarmes.', 'error');
      return;
    }

    const [h, m] = timeVal.split(':').map(Number);
    const selectedDays: number[] = [];
    dayPills.forEach((pill) => {
      if (pill.classList.contains('active')) {
        selectedDays.push(Number(pill.getAttribute('data-day')));
      }
    });

    settingsState.alarms.push({
      id: settingsState.alarms.length + 1,
      hours: h,
      minutes: m,
      enabled: true,
      snooze: inputSnooze ? inputSnooze.checked : true,
      days: selectedDays.sort()
    });

    renderAlarms();
    notifyFn('Alarme adicionado! Clique em "Sincronizar Alarmes" para gravar na pulseira.', 'info');
  });

  btnSync?.addEventListener('click', () => {
    saveAndSyncScope('alarms', 'progress-sync-alarms', 'Alarmes enviados com sucesso para a Mi Band!');
  });
}

function formatAlarmDays(days: number[]): string {
  if (!days || days.length === 0) return 'Uma vez (Hoje/Amanhã)';
  if (days.length === 7) return 'Todos os dias';
  if (days.length === 5 && days.every(d => [1, 2, 3, 4, 5].includes(d))) return 'Segunda a Sexta';
  if (days.length === 2 && days.every(d => [0, 6].includes(d))) return 'Finais de semana';

  const names = ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb'];
  return days.map(d => names[d]).join(', ');
}

function renderAlarms() {
  const container = document.getElementById('band-alarms-list');
  const badgeCount = document.getElementById('badge-alarms-count');
  if (!container) return;

  const list = settingsState.alarms || [];
  if (badgeCount) {
    badgeCount.textContent = `${list.length} de 10 alarmes`;
  }

  if (list.length === 0) {
    container.innerHTML = '<div class="band-empty-state">Nenhum alarme configurado. Adicione um acima ou clique em "Ler Alarmes da Pulseira".</div>';
    return;
  }

  container.innerHTML = '';
  list.forEach((alarm, idx) => {
    const pad = (n: number) => String(n).padStart(2, '0');
    const timeStr = `${pad(alarm.hours)}:${pad(alarm.minutes)}`;

    const item = document.createElement('div');
    item.className = 'alarm-item-card';
    item.innerHTML = `
      <div class="d-flex align-center gap-3">
        <label class="switch-wrap">
          <input type="checkbox" class="alarm-toggle-check" ${alarm.enabled ? 'checked' : ''}>
          <span class="slider round"></span>
        </label>
        <div>
          <div class="alarm-item-time">
            <span>⏰ ${timeStr}</span>
            ${alarm.snooze ? '<span class="alarm-badge-snooze">Soneca</span>' : ''}
          </div>
          <div class="alarm-item-days">${formatAlarmDays(alarm.days)}</div>
        </div>
      </div>
      <button type="button" class="btn-icon-delete" title="Excluir alarme">✕</button>
    `;

    const toggle = item.querySelector('.alarm-toggle-check') as HTMLInputElement;
    toggle?.addEventListener('change', () => {
      alarm.enabled = toggle.checked;
    });

    const btnDel = item.querySelector('.btn-icon-delete');
    btnDel?.addEventListener('click', () => {
      settingsState.alarms.splice(idx, 1);
      renderAlarms();
    });

    container.appendChild(item);
  });
}

// -------------------------------------------------------------
// 3. Relógio Mundial
// -------------------------------------------------------------
function setupWorldClocksSection() {
  const btnAdd = document.getElementById('btn-add-world-clock');
  const btnSync = document.getElementById('btn-sync-world-clocks');
  const inputCity = document.getElementById('input-world-city-name') as HTMLInputElement;
  const selectOffset = document.getElementById('select-world-city-offset') as HTMLSelectElement;

  btnAdd?.addEventListener('click', () => {
    const city = inputCity?.value?.trim();
    const offset = parseFloat(selectOffset?.value || '0');

    if (!city) {
      notifyFn('Digite o nome da cidade para adicionar.', 'info');
      inputCity?.focus();
      return;
    }

    if (!Array.isArray(settingsState.world_clocks)) {
      settingsState.world_clocks = [];
    }

    settingsState.world_clocks.push({
      city,
      timezone: offset
    });

    inputCity.value = '';
    renderWorldClocks();
    notifyFn('Cidade adicionada ao Relógio Mundial! Clique em "Sincronizar Relógios" para enviar à pulseira.', 'info');
  });

  btnSync?.addEventListener('click', () => {
    saveAndSyncScope('world_clocks', 'progress-sync-world-clocks', 'Relógio mundial sincronizado com a Mi Band!');
  });
}

function computeWorldClockTime(offsetHours: number): string {
  const now = new Date();
  const utc = now.getTime() + (now.getTimezoneOffset() * 60000);
  const targetDate = new Date(utc + (3600000 * offsetHours));
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${pad(targetDate.getHours())}:${pad(targetDate.getMinutes())}:${pad(targetDate.getSeconds())}`;
}

function updateWorldClocksTimeDisplay() {
  const list = settingsState.world_clocks || [];
  list.forEach((clock, idx) => {
    const el = document.getElementById(`wc-time-${idx}`);
    if (el) {
      el.textContent = computeWorldClockTime(clock.timezone);
    }
  });
}

function renderWorldClocks() {
  const container = document.getElementById('band-world-clocks-list');
  const badgeCount = document.getElementById('badge-world-clocks-count');
  if (!container) return;

  const list = settingsState.world_clocks || [];
  if (badgeCount) {
    badgeCount.textContent = `${list.length} cidade${list.length !== 1 ? 's' : ''}`;
  }

  if (list.length === 0) {
    container.innerHTML = '<div class="band-empty-state" style="grid-column: 1 / -1;">Nenhuma cidade cadastrada no Relógio Mundial.</div>';
    return;
  }

  container.innerHTML = '';
  list.forEach((clock, idx) => {
    const offsetStr = clock.timezone >= 0 ? `UTC+${clock.timezone}` : `UTC${clock.timezone}`;
    const card = document.createElement('div');
    card.className = 'world-clock-card';
    card.innerHTML = `
      <div>
        <div class="world-clock-city">${escapeHtml(clock.city)}</div>
        <div class="world-clock-offset">${offsetStr}</div>
      </div>
      <div class="d-flex align-center gap-2">
        <div class="world-clock-time" id="wc-time-${idx}">${computeWorldClockTime(clock.timezone)}</div>
        <button type="button" class="btn-icon-delete" title="Remover cidade">✕</button>
      </div>
    `;

    const btnDel = card.querySelector('.btn-icon-delete');
    btnDel?.addEventListener('click', () => {
      settingsState.world_clocks.splice(idx, 1);
      renderWorldClocks();
    });

    container.appendChild(card);
  });
}

// -------------------------------------------------------------
// 4. Levantar o Pulso
// -------------------------------------------------------------
function setupLiftWristSection() {
  const segmentBtns = document.querySelectorAll('#lift-wrist-mode-group .segment-btn');
  const scheduleWrap = document.getElementById('lift-wrist-schedule-wrap');
  const btnApply = document.getElementById('btn-apply-lift-wrist');

  segmentBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      segmentBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const mode = btn.getAttribute('data-mode');
      if (scheduleWrap) {
        scheduleWrap.style.display = mode === 'scheduled' ? 'flex' : 'none';
      }
    });
  });

  btnApply?.addEventListener('click', () => {
    saveAndSyncScope('wrist', 'progress-lift-wrist', 'Gesto de levantar o pulso configurado com sucesso!');
  });
}

// -------------------------------------------------------------
// 5. Modo Noturno & Não Perturbe
// -------------------------------------------------------------
function setupNightModeSection() {
  const selectNight = document.getElementById('select-night-mode') as HTMLSelectElement;
  const scheduleWrap = document.getElementById('night-mode-schedule-wrap');
  const btnApply = document.getElementById('btn-apply-night-mode');

  selectNight?.addEventListener('change', () => {
    if (scheduleWrap) {
      scheduleWrap.style.display = selectNight.value === 'scheduled' ? 'flex' : 'none';
    }
  });

  btnApply?.addEventListener('click', () => {
    saveAndSyncScope('night', 'progress-night-mode', 'Modo noturno e Não Perturbe aplicados na pulseira!');
  });
}

// -------------------------------------------------------------
// 6. Localização da Pulseira (Pulso Esquerdo / Direito)
// -------------------------------------------------------------
function setupWearLocationSection() {
  const wristCards = document.querySelectorAll('.wrist-card');
  const hiddenInput = document.getElementById('input-wear-location') as HTMLInputElement;
  const btnApply = document.getElementById('btn-apply-wear-location');

  wristCards.forEach((card) => {
    card.addEventListener('click', () => {
      wristCards.forEach(c => c.classList.remove('active'));
      card.classList.add('active');
      const wrist = card.getAttribute('data-wrist') || 'left';
      if (hiddenInput) hiddenInput.value = wrist;
    });
  });

  btnApply?.addEventListener('click', () => {
    saveAndSyncScope('wear_location', 'progress-wear-location', 'Localização da pulseira atualizada!');
  });
}

// -------------------------------------------------------------
// 7. Idioma da Pulseira
// -------------------------------------------------------------
function setupLanguageSection() {
  const btnApply = document.getElementById('btn-apply-language');

  btnApply?.addEventListener('click', () => {
    saveAndSyncScope('language', 'progress-band-language', 'Idioma da Mi Band alterado com sucesso!');
  });
}

// -------------------------------------------------------------
// Atualizar Controles da UI a partir do State
// -------------------------------------------------------------
function updateSystemControlsFromState() {
  // 4. Lift wrist
  const segmentBtns = document.querySelectorAll('#lift-wrist-mode-group .segment-btn');
  const scheduleWrapWrist = document.getElementById('lift-wrist-schedule-wrap');
  const inputWristStart = document.getElementById('input-lift-wrist-start') as HTMLInputElement;
  const inputWristEnd = document.getElementById('input-lift-wrist-end') as HTMLInputElement;
  const selectWristSpeed = document.getElementById('select-lift-wrist-speed') as HTMLSelectElement;

  segmentBtns.forEach(btn => {
    if (btn.getAttribute('data-mode') === settingsState.lift_wrist_mode) {
      btn.classList.add('active');
    } else {
      btn.classList.remove('active');
    }
  });
  if (scheduleWrapWrist) {
    scheduleWrapWrist.style.display = settingsState.lift_wrist_mode === 'scheduled' ? 'flex' : 'none';
  }
  if (inputWristStart) inputWristStart.value = settingsState.lift_wrist_start || '07:00';
  if (inputWristEnd) inputWristEnd.value = settingsState.lift_wrist_end || '22:00';
  if (selectWristSpeed) selectWristSpeed.value = settingsState.lift_wrist_speed || 'normal';

  // 5. Night Mode
  const selectNight = document.getElementById('select-night-mode') as HTMLSelectElement;
  const scheduleWrapNight = document.getElementById('night-mode-schedule-wrap');
  const inputNightStart = document.getElementById('input-night-mode-start') as HTMLInputElement;
  const inputNightEnd = document.getElementById('input-night-mode-end') as HTMLInputElement;
  const selectDnd = document.getElementById('select-dnd-mode') as HTMLSelectElement;

  if (selectNight) selectNight.value = settingsState.night_mode || 'sunset';
  if (scheduleWrapNight) {
    scheduleWrapNight.style.display = settingsState.night_mode === 'scheduled' ? 'flex' : 'none';
  }
  if (inputNightStart) inputNightStart.value = settingsState.night_mode_start || '22:00';
  if (inputNightEnd) inputNightEnd.value = settingsState.night_mode_end || '07:00';
  if (selectDnd) selectDnd.value = settingsState.dnd_mode || 'smart';

  // 6. Wear Location
  const wristCards = document.querySelectorAll('.wrist-card');
  const hiddenWrist = document.getElementById('input-wear-location') as HTMLInputElement;
  const currentWrist = settingsState.wear_location || 'left';
  if (hiddenWrist) hiddenWrist.value = currentWrist;
  wristCards.forEach(c => {
    if (c.getAttribute('data-wrist') === currentWrist) {
      c.classList.add('active');
    } else {
      c.classList.remove('active');
    }
  });

  // 7. Language
  const selectLang = document.getElementById('select-band-language') as HTMLSelectElement;
  if (selectLang) selectLang.value = settingsState.language || 'pt_BR';

  // Sincronizar visual dos comboboxes customizados
  syncCustomSelect('select-lift-wrist-speed');
  syncCustomSelect('select-night-mode');
  syncCustomSelect('select-dnd-mode');
  syncCustomSelect('select-band-language');
}

// -------------------------------------------------------------
// Coletar Dados do Formulário para o State
// -------------------------------------------------------------
function collectCurrentFormToState() {
  // Lift wrist
  const activeSegment = document.querySelector('#lift-wrist-mode-group .segment-btn.active');
  const mode = (activeSegment?.getAttribute('data-mode') || 'all_day') as any;
  settingsState.lift_wrist_mode = mode;

  const inputWristStart = document.getElementById('input-lift-wrist-start') as HTMLInputElement;
  const inputWristEnd = document.getElementById('input-lift-wrist-end') as HTMLInputElement;
  const selectWristSpeed = document.getElementById('select-lift-wrist-speed') as HTMLSelectElement;
  if (inputWristStart) settingsState.lift_wrist_start = inputWristStart.value;
  if (inputWristEnd) settingsState.lift_wrist_end = inputWristEnd.value;
  if (selectWristSpeed) settingsState.lift_wrist_speed = selectWristSpeed.value as any;

  // Night Mode
  const selectNight = document.getElementById('select-night-mode') as HTMLSelectElement;
  const inputNightStart = document.getElementById('input-night-mode-start') as HTMLInputElement;
  const inputNightEnd = document.getElementById('input-night-mode-end') as HTMLInputElement;
  const selectDnd = document.getElementById('select-dnd-mode') as HTMLSelectElement;
  if (selectNight) settingsState.night_mode = selectNight.value as any;
  if (inputNightStart) settingsState.night_mode_start = inputNightStart.value;
  if (inputNightEnd) settingsState.night_mode_end = inputNightEnd.value;
  if (selectDnd) settingsState.dnd_mode = selectDnd.value as any;

  // Wear Location
  const hiddenWrist = document.getElementById('input-wear-location') as HTMLInputElement;
  if (hiddenWrist) settingsState.wear_location = (hiddenWrist.value || 'left') as any;

  // Language
  const selectLang = document.getElementById('select-band-language') as HTMLSelectElement;
  if (selectLang) settingsState.language = selectLang.value;
}

function escapeHtml(str: string): string {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
