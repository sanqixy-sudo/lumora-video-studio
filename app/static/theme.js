// Apply before stylesheets; first paint never waits for an animation.
(function () {
  const root = document.documentElement;
  const modes = ['light', 'dark', 'system'];
  let preference = 'system', transition = null, cleanupTimer = null, revision = 0;
  try { preference = localStorage.getItem('sora.theme') || 'system'; } catch (_) {}
  if (!modes.includes(preference)) preference = 'system';
  const media = matchMedia('(prefers-color-scheme: dark)');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  function commit(value) {
    root.dataset.theme = value === 'system' ? (media.matches ? 'dark' : 'light') : value;
    root.dataset.themePreference = value;
    root.style.colorScheme = root.dataset.theme;
    let color = document.querySelector('meta[name=theme-color]');
    if (!color) { color = document.createElement('meta'); color.name = 'theme-color'; document.head.append(color); }
    color.content = root.dataset.theme === 'dark' ? '#141827' : '#F1F3FA';
    document.querySelectorAll('[data-theme-select]').forEach(select => { select.value = value; });
    dispatchEvent(new CustomEvent('lumora-theme-change', {detail: {preference: value, theme: root.dataset.theme}}));
  }
  function apply(value, animate = false) {
    preference = modes.includes(value) ? value : 'system';
    const requested = preference, current = ++revision;
    clearTimeout(cleanupTimer);
    transition?.skipTransition();
    transition = null;
    delete root.dataset.themeTransition;
    // Synchronize the requested mode immediately, including rapid repeated clicks.
    document.querySelectorAll('[data-theme-select]').forEach(select => { select.value = requested; });
    if (!animate || reduced.matches || document.hidden) { commit(requested); return; }
    if (document.startViewTransition) {
      root.dataset.themeTransition = 'view';
      transition = document.startViewTransition(() => { if (revision === current) commit(requested); });
      transition.ready.catch(() => {}); // Interrupted transitions still apply the latest preference.
      transition.finished.catch(() => {}).then(() => {
        if (revision === current) { delete root.dataset.themeTransition; transition = null; }
      });
    } else {
      root.dataset.themeTransition = 'css';
      // Establish transitions before changing the theme variables.
      void root.offsetWidth;
      commit(requested);
      cleanupTimer = setTimeout(() => { if (revision === current) delete root.dataset.themeTransition; }, 220);
    }
  }
  apply(preference);
  media.addEventListener('change', () => { if (preference === 'system') apply(preference, true); });
  reduced.addEventListener('change', () => { if (reduced.matches) apply(preference); });
  addEventListener('storage', event => {
    if (event.key === 'sora.theme' || event.key === null) apply(event.newValue || 'system', true);
  });
  document.addEventListener('DOMContentLoaded', () => {
    apply(preference);
    document.querySelectorAll('[data-theme-select]').forEach(select => {
      select.addEventListener('change', () => {
        const value = modes.includes(select.value) ? select.value : 'system';
        try { localStorage.setItem('sora.theme', value); } catch (_) {}
        apply(value, true);
      });
    });
  });
})();
