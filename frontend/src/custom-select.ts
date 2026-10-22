// Módulo Universal de Combobox Moderno (Custom Select Component)
// Transforma elementos <select class="modern-select"> em menus suspensos 100% integrados
// ao design Glassmorphism Dark do site, eliminando o popup nativo do sistema operacional.

export function initCustomSelects() {
  const selects = document.querySelectorAll<HTMLSelectElement>('select.modern-select');
  selects.forEach((select) => {
    enhanceSelect(select);
  });
}

export function syncCustomSelect(target: string | HTMLSelectElement) {
  const select = typeof target === 'string' ? document.getElementById(target) as HTMLSelectElement : target;
  if (!select) return;

  const wrapper = select.parentElement?.querySelector<HTMLElement>(`.custom-select-wrapper[data-for="${select.id}"]`);
  if (!wrapper) return;

  const selectedOption = select.selectedOptions[0] || select.options[0];
  const triggerLabel = wrapper.querySelector<HTMLElement>('.custom-select-label');
  if (triggerLabel && selectedOption) {
    triggerLabel.textContent = selectedOption.textContent;
  }

  const options = wrapper.querySelectorAll<HTMLElement>('.custom-select-option');
  options.forEach((opt) => {
    if (opt.getAttribute('data-value') === select.value) {
      opt.classList.add('selected');
    } else {
      opt.classList.remove('selected');
    }
  });
}

export function refreshCustomSelectOptions(target: string | HTMLSelectElement) {
  const select = typeof target === 'string' ? document.getElementById(target) as HTMLSelectElement : target;
  if (!select) return;

  const wrapper = select.parentElement?.querySelector<HTMLElement>(`.custom-select-wrapper[data-for="${select.id}"]`);
  if (!wrapper) return;

  const menu = wrapper.querySelector<HTMLElement>('.custom-select-dropdown');
  if (!menu) return;

  // Re-render options from native select
  menu.innerHTML = '';
  Array.from(select.options).forEach((opt) => {
    const optDiv = document.createElement('div');
    optDiv.className = `custom-select-option ${opt.selected ? 'selected' : ''}`;
    optDiv.setAttribute('data-value', opt.value);
    optDiv.setAttribute('role', 'option');
    optDiv.innerHTML = `
      <span class="option-text">${escapeHtml(opt.textContent || '')}</span>
      <span class="option-check">✓</span>
    `;

    optDiv.addEventListener('click', (e) => {
      e.stopPropagation();
      selectOption(select, wrapper, opt.value, opt.textContent || '');
    });

    menu.appendChild(optDiv);
  });

  syncCustomSelect(select);
}

function enhanceSelect(select: HTMLSelectElement) {
  // Evitar duplicidade caso já tenha sido processado
  if (select.dataset.customEnhanced === 'true') {
    syncCustomSelect(select);
    return;
  }

  select.dataset.customEnhanced = 'true';
  select.style.display = 'none';

  // Criar Wrapper
  const wrapper = document.createElement('div');
  wrapper.className = 'custom-select-wrapper';
  wrapper.setAttribute('data-for', select.id);

  // Criar Botão Gatilho (Trigger)
  const trigger = document.createElement('button');
  trigger.type = 'button';
  trigger.className = 'custom-select-trigger';
  trigger.setAttribute('aria-haspopup', 'listbox');
  trigger.setAttribute('aria-expanded', 'false');

  const selectedOpt = select.selectedOptions[0] || select.options[0];
  const initialText = selectedOpt ? selectedOpt.textContent || '' : 'Selecione...';

  trigger.innerHTML = `
    <span class="custom-select-label">${escapeHtml(initialText)}</span>
    <span class="custom-select-arrow"></span>
  `;

  // Criar Menu Suspenso (Dropdown List)
  const dropdown = document.createElement('div');
  dropdown.className = 'custom-select-dropdown';
  dropdown.setAttribute('role', 'listbox');

  // Adicionar opções baseadas no select nativo
  Array.from(select.options).forEach((opt) => {
    const optDiv = document.createElement('div');
    optDiv.className = `custom-select-option ${opt.selected ? 'selected' : ''}`;
    optDiv.setAttribute('data-value', opt.value);
    optDiv.setAttribute('role', 'option');
    optDiv.innerHTML = `
      <span class="option-text">${escapeHtml(opt.textContent || '')}</span>
      <span class="option-check">✓</span>
    `;

    optDiv.addEventListener('click', (e) => {
      e.stopPropagation();
      selectOption(select, wrapper, opt.value, opt.textContent || '');
    });

    dropdown.appendChild(optDiv);
  });

  // Abrir / Fechar ao clicar no trigger
  trigger.addEventListener('click', (e) => {
    e.stopPropagation();
    const isOpen = wrapper.classList.contains('open');
    closeAllCustomSelects();
    if (!isOpen) {
      wrapper.classList.add('open');
      trigger.setAttribute('aria-expanded', 'true');
      
      // Rolar menu para a opção atualmente selecionada
      const activeOpt = dropdown.querySelector('.custom-select-option.selected') as HTMLElement;
      if (activeOpt) {
        dropdown.scrollTop = activeOpt.offsetTop - dropdown.offsetTop - 20;
      }
    }
  });

  // Suporte a teclado no trigger
  trigger.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp' || e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      if (!wrapper.classList.contains('open')) {
        wrapper.classList.add('open');
        trigger.setAttribute('aria-expanded', 'true');
      } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        navigateOptions(select, wrapper, e.key === 'ArrowDown' ? 1 : -1);
      } else if (e.key === 'Enter' || e.key === ' ') {
        wrapper.classList.remove('open');
        trigger.setAttribute('aria-expanded', 'false');
      }
    } else if (e.key === 'Escape' && wrapper.classList.contains('open')) {
      e.preventDefault();
      wrapper.classList.remove('open');
      trigger.setAttribute('aria-expanded', 'false');
    }
  });

  wrapper.appendChild(trigger);
  wrapper.appendChild(dropdown);

  // Inserir após o select nativo
  select.parentElement?.insertBefore(wrapper, select.nextSibling);

  // Interceptar setter nativo do select.value para manter UI sincronizada em tempo real
  hookSelectValueSetter(select, () => {
    syncCustomSelect(select);
  });
}

function selectOption(select: HTMLSelectElement, wrapper: HTMLElement, value: string, text: string) {
  const previousValue = select.value;
  select.value = value;

  const triggerLabel = wrapper.querySelector<HTMLElement>('.custom-select-label');
  if (triggerLabel) {
    triggerLabel.textContent = text;
  }

  const options = wrapper.querySelectorAll<HTMLElement>('.custom-select-option');
  options.forEach((opt) => {
    if (opt.getAttribute('data-value') === value) {
      opt.classList.add('selected');
    } else {
      opt.classList.remove('selected');
    }
  });

  wrapper.classList.remove('open');
  const trigger = wrapper.querySelector<HTMLElement>('.custom-select-trigger');
  if (trigger) trigger.setAttribute('aria-expanded', 'false');

  // Disparar evento 'change' nativo caso o valor tenha mudado
  if (previousValue !== value) {
    select.dispatchEvent(new Event('change', { bubbles: true }));
  }
}

function navigateOptions(select: HTMLSelectElement, wrapper: HTMLElement, direction: number) {
  const options = Array.from(wrapper.querySelectorAll<HTMLElement>('.custom-select-option'));
  if (options.length === 0) return;

  const currentIndex = options.findIndex((opt) => opt.classList.contains('selected'));
  let newIndex = currentIndex + direction;

  if (newIndex < 0) newIndex = 0;
  if (newIndex >= options.length) newIndex = options.length - 1;

  const targetOpt = options[newIndex];
  if (targetOpt) {
    const val = targetOpt.getAttribute('data-value') || '';
    const txt = targetOpt.querySelector('.option-text')?.textContent || '';
    selectOption(select, wrapper, val, txt);
  }
}

function closeAllCustomSelects() {
  document.querySelectorAll('.custom-select-wrapper.open').forEach((w) => {
    w.classList.remove('open');
    w.querySelector('.custom-select-trigger')?.setAttribute('aria-expanded', 'false');
  });
}

// Fechar ao clicar fora
if (typeof document !== 'undefined') {
  document.addEventListener('click', (e) => {
    const target = e.target as HTMLElement;
    if (!target.closest('.custom-select-wrapper')) {
      closeAllCustomSelects();
    }
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      closeAllCustomSelects();
    }
  });
}

// Interceptar o setter .value no elemento select para reatividade automática
function hookSelectValueSetter(select: HTMLSelectElement, onChange: () => void) {
  const descriptor = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value');
  if (descriptor && descriptor.set && descriptor.get) {
    const originalSet = descriptor.set;
    const originalGet = descriptor.get;

    Object.defineProperty(select, 'value', {
      set(val) {
        originalSet.call(this, val);
        onChange();
      },
      get() {
        return originalGet.call(this);
      },
      configurable: true
    });
  }
}

function escapeHtml(str: string): string {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
