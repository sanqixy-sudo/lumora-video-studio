/* Icon controls enhance the existing select, preserving theme state and integrations. */
(() => {
  const icons = {
    light: '<path d="M12 3v2.25m0 13.5V21M3 12h2.25m13.5 0H21M5.636 5.636l1.591 1.591m9.546 9.546 1.591 1.591M5.636 18.364l1.591-1.591m9.546-9.546 1.591-1.591"/><circle cx="12" cy="12" r="4.5"/>',
    dark: '<path d="M21.75 15.002A9.72 9.72 0 0 1 18 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.75A9.753 9.753 0 0 0 2.25 11.5c0 5.385 4.365 9.75 9.75 9.75a9.753 9.753 0 0 0 9.75-6.248Z"/>',
    system: '<rect x="2.25" y="3.75" width="19.5" height="13.5" rx="1.5"/><path d="M8.25 21h7.5M9.75 17.25 9 21m5.25-3.75L15 21M2.25 13.5h19.5"/>'
  };
  const labels = {light:'浅色', dark:'深色', system:'跟随系统'};
  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('select[data-theme-select]').forEach(select => {
      if (select.closest('.theme-icon-switch')) return;
      const group = document.createElement('div');
      group.className = 'theme-icon-switch'; group.setAttribute('role', 'group'); group.setAttribute('aria-label', '外观主题');
      const label = select.closest('label');
      (label || select).replaceWith(group);
      select.hidden = true; select.tabIndex = -1; group.append(select);
      const buttons = Object.keys(labels).map(value => {
        const button = document.createElement('button');
        button.type = 'button'; button.className = 'theme-icon-button'; button.dataset.themeOption = value;
        button.title = labels[value]; button.setAttribute('aria-label', labels[value]);
        button.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[value]}</svg>`;
        button.addEventListener('click', () => {
          select.value = value;
          select.dispatchEvent(new Event('change', {bubbles:true}));
        });
        group.append(button); return button;
      });
      function sync() {
        buttons.forEach(button => {
          const selected = button.dataset.themeOption === select.value;
          button.setAttribute('aria-pressed', String(selected)); button.tabIndex = selected ? 0 : -1;
        });
      }
      group.addEventListener('keydown', event => {
        if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
        const index = buttons.indexOf(document.activeElement); if (index < 0) return;
        event.preventDefault();
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? 2 : (index + (event.key === 'ArrowRight' ? 1 : 2)) % 3;
        buttons[next].focus({preventScroll:true}); buttons[next].click();
      });
      select.addEventListener('change', sync); sync();
    });
  });
})();
