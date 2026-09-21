/* One native button cycles all three modes; the select remains the integration point. */
(() => {
  const icons = {
    light: '<path d="M12 3v2m0 14v2M3 12h2m14 0h2M5.6 5.6 7 7m10 10 1.4 1.4M5.6 18.4 7 17m10-10 1.4-1.4"/><circle cx="12" cy="12" r="4.5"/>',
    dark: '<path d="M20.8 14.6A8.8 8.8 0 0 1 9.4 3.2 9 9 0 1 0 20.8 14.6Z"/>',
    system: '<path d="M12 3v2m0 14v2M3 12h2M5.6 5.6 7 7M5.6 18.4 7 17"/><path d="M12 6a6 6 0 1 0 0 12V6Z"/><path d="M15 5.2a7 7 0 0 0 5.8 10.1A8.5 8.5 0 0 1 12 20"/>'
  };
  const modes = ['light', 'dark', 'system'];
  const labels = {light: '浅色', dark: '深色', system: '跟随系统'};
  function initThemeControls() {
    document.querySelectorAll('select[data-theme-select]').forEach((select, index) => {
      if (select.closest('.theme-cycle-control')) return;
      select.value = document.documentElement.dataset.themePreference || 'system';
      const group = document.createElement('div');
      group.className = 'theme-cycle-control';
      const label = select.closest('label');
      (label || select).replaceWith(group);
      select.hidden = true; select.tabIndex = -1; group.append(select);
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'theme-cycle-button';
      const stack = document.createElement('span');
      stack.className = 'theme-icon-stack'; stack.setAttribute('aria-hidden', 'true');
      if (index === 0) stack.style.viewTransitionName = 'theme-mode-icon';
      for (const mode of modes) {
        const icon = document.createElement('span');
        icon.className = 'theme-toggle-icon'; icon.dataset.icon = mode;
        icon.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${icons[mode]}</svg>`;
        stack.append(icon);
      }
      button.append(stack);
      const status = document.createElement('span');
      status.className = 'theme-cycle-status'; status.setAttribute('role', 'status');
      group.append(button, status);
      function sync(announce = false) {
        const mode = select.value || 'system';
        const next = modes[(modes.indexOf(mode) + 1) % modes.length];
        button.dataset.mode = mode;
        const resolved = document.documentElement.dataset.theme === 'dark' ? '深色' : '浅色';
        const currentLabel = labels[mode] + (mode === 'system' ? '（' + resolved + '）' : '');
        button.title = currentLabel + ' · 点击切换为' + labels[next];
        button.setAttribute('aria-label', '当前' + currentLabel + '，点击切换为' + labels[next]);
        if (announce) status.textContent = '外观已设为' + currentLabel;
      }
      button.addEventListener('click', () => {
        select.value = modes[(modes.indexOf(select.value) + 1) % modes.length];
        select.dispatchEvent(new Event('change', {bubbles: true}));
      });
      addEventListener('lumora-theme-change', () => sync(true));
      sync();
    });
  }
  if (document.body) initThemeControls();
  else document.addEventListener('DOMContentLoaded', initThemeControls, {once:true});
})();
