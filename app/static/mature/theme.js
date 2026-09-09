// Apply before stylesheets to avoid a light flash on dark-theme pages.
(function () {
  let preference = 'system';
  try { preference = localStorage.getItem('sora.theme') || 'system'; } catch (_) {}
  if (!['light', 'dark', 'system'].includes(preference)) preference = 'system';
  const media = window.matchMedia('(prefers-color-scheme: dark)');
  function apply(value) {
    preference = value;
    document.documentElement.dataset.theme = value === 'system' ? (media.matches ? 'dark' : 'light') : value;
    document.documentElement.style.colorScheme = document.documentElement.dataset.theme;
    let color=document.querySelector('meta[name=theme-color]');if(!color){color=document.createElement('meta');color.name='theme-color';document.head.append(color);}color.content=document.documentElement.dataset.theme==='dark'?'#151620':'#F2F3F8';
    document.querySelectorAll('[data-theme-select]').forEach(select => { select.value = value; });
  }
  apply(preference);
  media.addEventListener('change', () => apply(preference));
  document.addEventListener('DOMContentLoaded', () => {
    apply(preference);
    document.querySelectorAll('[data-theme-select]').forEach(select => {
      select.addEventListener('change', () => {
        try { localStorage.setItem('sora.theme', select.value); } catch (_) {}
        apply(select.value);
      });
    });
  });
})();
