/* Native document navigation remains in charge of URLs, history and form protection. */
(() => {
  const root = document.documentElement;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  let pendingLink = null, delay = null, slow = null, timeout = null, pageTransition = null;
  const workspace = value => {
    try {
      const url = new URL(value, location.href);
      return url.origin === location.origin && (['/', '/login'].includes(url.pathname) || /^\/(?:app|admin)(?:\/|$)/.test(url.pathname) &&
        (url.pathname === '/app' || url.pathname === '/admin' || url.pathname.endsWith('/page')));
    } catch (_) { return false; }
  };
  function clearPending() {
    clearTimeout(delay); clearTimeout(slow); clearTimeout(timeout);
    delete root.dataset.navigationPending; delete root.dataset.navigationSlow;
    pendingLink?.classList.remove('is-navigating');
    pendingLink?.removeAttribute('aria-busy');
    pendingLink = null;
    const status = document.getElementById('wb-navigation-status');
    if (status) status.textContent = '';
  }
  function pending(link) {
    clearPending();
    pendingLink = link;
    link?.classList.add('is-navigating'); link?.setAttribute('aria-busy', 'true');
    // Avoid flashing a loader for fast local responses. No fake completion percentage.
    delay = setTimeout(() => {
      root.dataset.navigationPending = 'true';
      const status = document.getElementById('wb-navigation-status');
      if (status) status.textContent = '正在打开' + (link?.textContent.trim() || '页面') + '…';
    }, 140);
    // Show a readable label only when the wait is noticeable.
    slow = setTimeout(() => {root.dataset.navigationSlow = 'true';}, 600);
    // Legacy engines lack navigateerror; keep their fallback from sticking after a browser-level cancel.
    if (!window.navigation) timeout = setTimeout(clearPending, 15000);
  }
  function restoreSidebar() {
    try {
      document.body?.classList.toggle('wb-nav-collapsed', localStorage.getItem('sora.nav.collapsed') === 'true');
      const nav = document.querySelector('.wb-nav');
      if (nav) nav.scrollTop = Number(sessionStorage.getItem('lumora.nav-scroll.' + document.body.dataset.role)) || 0;
    } catch (_) {}
  }
  function finishTransition(transition) {
    transition.ready.catch(() => {});
    transition.updateCallbackDone?.catch(() => {});
    transition.finished.catch(() => {}).then(() => {
      if (pageTransition === transition) {
        delete root.dataset.pageTransition; pageTransition = null;
      }
    });
  }
  // A short content entrance is also available in browsers without cross-document transitions.
  try {
    const navigationType = performance.getEntriesByType('navigation')[0]?.type;
    if (workspace(document.referrer) && navigationType === 'navigate' && !reduced.matches) root.dataset.pageEnter = 'true';
  } catch (_) {}
  addEventListener('pageswap', event => {
    const transition = event.viewTransition;
    try {
      const nav = document.querySelector('.wb-nav');
      if (nav) sessionStorage.setItem('lumora.nav-scroll.' + document.body.dataset.role, String(nav.scrollTop));
    } catch (_) {}
    clearPending();
    if (!transition) return;
    if (reduced.matches) {
      pageTransition = transition; finishTransition(pageTransition);
      transition.skipTransition(); return;
    }
    root.dataset.pageTransition = 'true';
    // A mobile navigation drawer should not remain in the outgoing page snapshot.
    document.querySelectorAll('.wb-mobile-nav-dialog[open]').forEach(dialog => dialog.close());
    pageTransition = transition; finishTransition(pageTransition);
  });
  addEventListener('pagereveal', event => {
    const transition = event.viewTransition;
    clearPending(); restoreSidebar();
    if (!transition) return;
    delete root.dataset.pageEnter;
    if (reduced.matches) {
      pageTransition = transition; finishTransition(pageTransition);
      transition.skipTransition(); return;
    }
    root.dataset.pageTransition = 'true';
    pageTransition = transition; finishTransition(pageTransition);
  });
  addEventListener('pageshow', () => {
    clearPending(); restoreSidebar();
    if (!pageTransition) delete root.dataset.pageTransition;
    setTimeout(() => { delete root.dataset.pageEnter; }, 240);
  });
  addEventListener('pagehide', clearPending);
  window.navigation?.addEventListener('navigateerror', clearPending);
  window.navigation?.addEventListener('navigate', event => {
    if (!event.destination.sameDocument && !event.downloadRequest && workspace(event.destination.url)) pending(null);
  });
  document.addEventListener('visibilitychange', () => {root.toggleAttribute('data-navigation-hidden', document.hidden);});
  // Do not leave a spinner behind when the existing unsaved-changes prompt is cancelled.
  addEventListener('beforeunload', event => queueMicrotask(() => {if (event.defaultPrevented) clearPending();}));
  reduced.addEventListener('change', () => {
    if (reduced.matches) {pageTransition?.skipTransition(); delete root.dataset.pageEnter;}
  });
  document.addEventListener('keydown', event => {if (event.key === 'Escape') clearPending();});
  document.addEventListener('DOMContentLoaded', () => {
    restoreSidebar();
    const status = document.createElement('span');
    status.id = 'wb-navigation-status'; status.className = 'wb-navigation-status';
    status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    document.body.append(status);
    const bar = document.createElement('div');
    bar.className = 'wb-navigation-progress'; bar.setAttribute('aria-hidden', 'true');
    document.body.append(bar);
    document.addEventListener('submit', event => {
      const form = event.target, submitter = event.submitter;
      const method = submitter?.getAttribute('formmethod') || form.method;
      const target = submitter?.getAttribute('formtarget') || form.target;
      const action = submitter?.getAttribute('formaction') || form.action;
      if (method.toLowerCase() !== 'get' || (target && target !== '_self') || !workspace(action)) return;
      queueMicrotask(() => {if (!event.defaultPrevented) pending(null);});
    });
    document.addEventListener('click', event => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const link = event.target.closest('a[href]');
      if (!link || link.hasAttribute('download') || (link.target && link.target !== '_self') || !workspace(link.href)) return;
      const destination = new URL(link.href);
      if (destination.pathname === location.pathname && destination.search === location.search) return;
      // Observe the final click result; never intercept navigation or delay the network request.
      queueMicrotask(() => {if (!event.defaultPrevented) pending(link);});
    });
  });
})();
