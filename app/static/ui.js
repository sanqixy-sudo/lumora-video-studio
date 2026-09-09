/* Small shared UI primitives. No persistent draft or server configuration storage. */
const SoraUI = (() => {
  let toastTimer;
  let pendingDialog = null;
  let fieldErrorId = 0;
  const feedbacks=new WeakMap();
  const modalOrigins=new WeakMap();
  function setModalOrigin(modal,trigger){if(modal&&trigger)modalOrigins.set(modal,trigger);}
  function feedback(button,text='已完成') {
    let state=feedbacks.get(button);
    if(!state){state={html:button.innerHTML};feedbacks.set(button,state);}
    clearTimeout(state.timer);button.textContent=text;button.dataset.feedback='success';
    state.timer=setTimeout(()=>{button.innerHTML=state.html;delete button.dataset.feedback;feedbacks.delete(button);},1200);
  }
  function message(error) {
    if (Array.isArray(error)) return error.map(item => `${(item.loc || []).slice(1).join(' / ')} ${item.msg || ''}`).join('\n');
    if (error && typeof error === 'object') return error.message || JSON.stringify(error);
    return String(error || '操作失败，请重试。');
  }
  function toast(value, type = 'info') {
    let element = document.getElementById('app-toast');
    if (!element) { element = document.createElement('div'); element.id = 'app-toast'; document.body.append(element); }
    element.className = `app-toast app-toast-${type}`;
    element.setAttribute('role', type === 'error' ? 'alert' : 'status');element.setAttribute('aria-live','polite');
    element.replaceChildren();
    const text = document.createElement('span'); text.textContent = message(value);
    const close = document.createElement('button'); close.type = 'button'; close.className = 'toast-dismiss'; close.setAttribute('aria-label', '关闭提示'); close.textContent = '×'; close.onclick = () => element.classList.add('hidden');
    element.append(text, close);
    clearTimeout(toastTimer);
    if (type !== 'error') toastTimer = setTimeout(() => element.classList.add('hidden'), 3500);
  }
  function formError(form, error) {
    let block = form.querySelector('[data-form-error],#studio-form-error');
    if (!block) { block = document.createElement('div'); block.dataset.formError = ''; block.className = 'form-error'; block.setAttribute('role', 'alert'); block.tabIndex = -1; form.prepend(block); }
    block.setAttribute('aria-live','polite');block.textContent = message(error?.message || error); block.classList.remove('hidden'); block.focus({preventScroll:true}); block.scrollIntoView({block:'nearest',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});
    form.querySelectorAll('.field-error').forEach(note => {
      form.querySelectorAll('[aria-describedby]').forEach(control=>{const ids=control.getAttribute('aria-describedby').split(/\s+/).filter(id=>id!==note.id);if(ids.length)control.setAttribute('aria-describedby',ids.join(' '));else control.removeAttribute('aria-describedby');});note.remove();
    });
    form.querySelectorAll('[aria-invalid=true]').forEach(node => node.removeAttribute('aria-invalid'));
    if (Array.isArray(error?.detail)) error.detail.forEach(item => {
      const control = form.elements.namedItem(item.loc?.[item.loc.length - 1]);
      if (!(control instanceof HTMLElement)) return;
      control.setAttribute('aria-invalid','true');queueMicrotask(()=>{const first=form.querySelector('[aria-invalid=true]'),panel=first?.closest('[data-tab-panel]');if(panel&&!panel.classList.contains('active'))form.querySelector('[data-tab-target='+panel.dataset.tabPanel+']')?.click();first?.focus();});
      const note = document.createElement('small'); note.className = 'field-error'; note.textContent = item.msg; note.id=`field-error-${++fieldErrorId}`;control.setAttribute('aria-describedby',[control.getAttribute('aria-describedby'),note.id].filter(Boolean).join(' '));control.after(note);
    });
  }
  function confirmDialog(text, options = {}) {
    if (pendingDialog) return Promise.resolve(false);
    return new Promise(resolve => {
      const previousFocus = document.activeElement;
      const dialog = document.createElement('dialog'); dialog.className = 'confirm-dialog'; dialog.setAttribute('aria-labelledby','confirm-title');
      const heading = document.createElement('h3'); heading.id = 'confirm-title'; heading.textContent = options.title || '确认操作';
      const description = document.createElement('p'); description.id = 'confirm-description'; description.textContent = text; dialog.setAttribute('aria-describedby', description.id);
      dialog.append(heading, description);
      let input;
      if (options.expected) { input = document.createElement('input'); input.placeholder = '输入账号名…'; input.name='confirm_username';input.spellcheck=false; input.setAttribute('aria-label','确认账号名'); input.autocomplete = 'off'; dialog.append(input); }
      const actions = document.createElement('div'); actions.className = 'inline-actions';
      const cancel = document.createElement('button'); cancel.type = 'button'; cancel.className = 'ghost-btn'; cancel.textContent = '取消';
      const submit = document.createElement('button'); submit.type = 'button'; submit.className = options.danger ? 'danger-btn' : 'primary-btn'; submit.textContent = options.label || '确认';
      if (input) { submit.disabled = true; input.addEventListener('input', () => submit.disabled = input.value !== options.expected); }
      actions.append(cancel, submit); dialog.append(actions); document.body.append(dialog); pendingDialog = dialog;
      let done = false;
      function finish(result) { if (done) return; done = true; dialog.close(); if (document.body.classList.contains("wb")) setTimeout(() => dialog.remove(), 160); else dialog.remove(); pendingDialog = null; previousFocus?.focus(); resolve(result); }
      cancel.onclick = () => finish(false); submit.onclick = () => finish(true);
      dialog.addEventListener('cancel', event => { event.preventDefault(); finish(false); });
      if(!matchMedia('(min-width:768px)').matches)cancel.autofocus=true;
      dialog.showModal(); (matchMedia('(min-width:768px)').matches&&input || cancel).focus();
    });
  }
  async function submitForm(form, submitter) {
    const button = submitter || form.querySelector('button[type=submit]');
    const original = button?.innerHTML;
    if (button) { button.disabled = true; button.textContent = '正在保存…'; button.setAttribute('aria-busy','true'); }
    try {
      const data = new FormData(form);
      if (submitter?.name) data.append(submitter.name, submitter.value);
      // Empty multipart forms are rejected by some reverse proxies (including BT WAF).
      // Use standard URL encoding unless the form actually contains a file control.
      const hasFile = [...data.values()].some(value => value instanceof File);
      const body = hasFile ? data : new URLSearchParams([...data.entries()]);
      const response = await fetch(form.action, {method:'POST',body,credentials:'same-origin'});
      const contentType = response.headers.get('content-type') || '';
      if (response.status === 401) { window.location.assign(`/login?next=${encodeURIComponent(location.pathname + location.search)}&expired=1`); return; }
      if (!response.ok) {
        const detail = contentType.includes('json') ? (await response.json()).detail : `保存失败（HTTP ${response.status}）`;
        const error = new Error(message(detail)); error.detail = detail; throw error;
      }
      if (contentType.includes('json')) {
        const result = await response.json();
        if (!result || typeof result !== 'object' || Array.isArray(result)) throw new Error('服务器或网关返回异常，操作未确认保存。');
        if (result?.ok === false || result?.success === false) throw new Error(message(result.detail || result.message || '保存失败，请重试。'));
        if (!result.target && result.ok !== true && result.success !== true) throw new Error(message(result.detail || result.message || '服务器未确认保存结果。'));
        if (result?.target) { document.dispatchEvent(new CustomEvent('lumora:saved',{detail:{form}}));window.location.assign(result.target); return; }
      } else {
        const page = new DOMParser().parseFromString(await response.text(), 'text/html');
        if (!response.redirected) throw new Error('服务器未确认保存结果，请刷新页面后重试。');
        const alert = page.querySelector('.login-alert,[data-form-error]:not(.hidden)');
        if (alert) throw new Error(alert.textContent);
        if (response.redirected && new URL(response.url).pathname === '/login') { window.location.assign(response.url); return; }
      }
      document.dispatchEvent(new CustomEvent('lumora:saved',{detail:{form}}));
      try {
        if (!new URL(response.url).searchParams.has('notice')) {
          sessionStorage.setItem('app.toast.message','操作已保存'); sessionStorage.setItem('app.toast.type','info');
        } else { sessionStorage.removeItem('app.toast.message'); sessionStorage.removeItem('app.toast.type'); }
      } catch (_) {}
      const target = new URL(response.redirected ? response.url : location.href);
      if (target.pathname === location.pathname) { target.search = target.search || location.search; target.hash = location.hash || target.hash; }
      window.location.assign(target.href);
    } catch (error) { formError(form,error); }
    finally { if (button) { button.disabled = false; button.innerHTML = original; button.removeAttribute('aria-busy'); } }
  }
  document.addEventListener('submit', async event => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || form.method.toLowerCase() !== 'post' || form.id === 'create-job-form' || form.dataset.asyncJson || form.hasAttribute('data-native-submit')) return;
    event.preventDefault();
    if (form.dataset.busy === 'true') return;
    form.dataset.busy = 'true';
    try {
      const expected = form.dataset.confirmUsername;
      const text = form.dataset.confirmMessage || form.dataset.confirmSubmit || (expected ? `删除账号 ${expected}。请输入账号名确认。` : '');
      if (text && !await confirmDialog(text, {expected,danger:true})) return;
      if (expected) form.elements.namedItem('confirm_username').value = expected;
      await submitForm(form, event.submitter);
    } finally { delete form.dataset.busy; }
  }, true);
  document.addEventListener('DOMContentLoaded', () => {
    const listPaths = ['/admin/users/page','/admin/jobs/page','/admin/job-batches/page','/app/jobs/page','/app/job-batches/page','/app/library/page'];
    try {
      if (listPaths.includes(location.pathname)) sessionStorage.setItem('sora.return.'+location.pathname,location.pathname+location.search);
      document.querySelectorAll('.page-head a[href],.wb-page-heading a[href]').forEach(link => {
        const href=link.getAttribute('href');
        if (listPaths.includes(href)) { const saved=sessionStorage.getItem('sora.return.'+href); if (saved && new URL(saved,location.origin).pathname===href) link.href=saved; }
      });
    } catch (_) {}
    const menu = document.querySelector('.mobile-menu-toggle');
    function closeNav() { document.body.classList.remove('nav-open'); menu?.setAttribute('aria-expanded','false'); }
    menu?.addEventListener('click', () => { const open = document.body.classList.toggle('nav-open'); menu.setAttribute('aria-expanded',String(open)); });
    document.addEventListener('keydown', event => { if (event.key === 'Escape') { closeNav(); document.querySelectorAll('.modal:not(.hidden) [data-close-usage],.modal:not(.hidden) [data-close-modal],.plaza-modal:not(.hidden) [data-close-plaza]').forEach(button => button.click()); } });
    document.addEventListener('click', event => { if (!event.target.closest('.sidebar,.mobile-menu-toggle')) closeNav(); });
    // Existing custom modals keep their behavior and gain focus management.
    document.querySelectorAll('.modal,.plaza-modal').forEach(modal => {
      // A dialog must live outside the background subtree that becomes inert.
      if(modal.closest('.wb-shell'))document.body.append(modal);
      modal.setAttribute('role','dialog'); modal.setAttribute('aria-modal','true');
      modal.setAttribute('aria-label', modal.querySelector('h2,h3')?.textContent || '详情');
      let previous;
      new MutationObserver(() => {
        modal.inert=modal.classList.contains('hidden');
        const shell=document.querySelector('.wb-shell');if(shell)shell.inert=!modal.inert;
        if (!modal.classList.contains('hidden')) { previous = modalOrigins.get(modal)||document.activeElement; modal.querySelector('button,input,select,[tabindex]')?.focus(); }
        else if (previous) { previous.focus({preventScroll:true}); previous = null; modalOrigins.delete(modal); }
      }).observe(modal,{attributes:true,attributeFilter:['class']});
      modal.addEventListener('keydown', event => {
        if (event.key !== 'Tab') return;
        const focusable = [...modal.querySelectorAll('button,a[href],input,select,textarea,[tabindex="0"]')].filter(el => !el.disabled && el.getClientRects().length);
        const first = focusable[0], last = focusable.at(-1);
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      });
    });
  });
  return {toast,formError,message,feedback,setModalOrigin,confirm:confirmDialog};
})();
