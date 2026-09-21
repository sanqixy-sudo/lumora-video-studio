/* Progressive select enhancement. Native controls remain the source of form values. */
(() => {
  let active = null, sequence = 0;
  const instances = new WeakMap();
  function enhance(select) {
    if (instances.has(select) || select.multiple || select.size > 1 ||
        select.matches('[hidden],[data-theme-select],[data-native-select]')) return;
    const id = 'lumora-select-' + ++sequence;
    const labels = [...select.labels || []];
    const title = select.getAttribute('aria-label') || labels.map(label => {
      const copy = label.cloneNode(true);
      copy.querySelectorAll('select,input,button,.soft-select').forEach(el => el.remove());
      return copy.textContent.trim();
    }).join(' ') || '选择选项';
    const wrap = document.createElement('span'); wrap.className = 'soft-select';
    const trigger = document.createElement('div');
    trigger.className = 'soft-select-trigger'; trigger.tabIndex = 0;
    trigger.id = id; trigger.setAttribute('role', 'combobox');
    trigger.setAttribute('aria-haspopup', 'listbox'); trigger.setAttribute('aria-expanded', 'false');
    trigger.setAttribute('aria-label', title); trigger.setAttribute('aria-controls', id + '-list');
    if (select.hasAttribute('aria-describedby')) trigger.setAttribute('aria-describedby', select.getAttribute('aria-describedby'));
    const caption = document.createElement('span'); caption.className = 'soft-select-value';
    const arrow = document.createElement('span'); arrow.className = 'soft-select-arrow'; arrow.setAttribute('aria-hidden', 'true');
    trigger.append(caption, arrow);
    const panel = document.createElement('div'); panel.id = id + '-list';
    panel.className = 'soft-select-menu'; panel.setAttribute('role', 'listbox'); panel.setAttribute('aria-label', title);
    panel.setAttribute('aria-hidden', 'true');
    if (panel.showPopover) panel.setAttribute('popover', 'manual');
    const error = document.createElement('span'); error.id = id + '-error'; error.className = 'soft-select-error'; error.hidden = true;
    error.setAttribute('aria-live', 'polite');
    select.before(wrap); wrap.append(select, trigger, error);
    select.classList.add('soft-select-native'); select.tabIndex = -1; select.setAttribute('aria-hidden', 'true');
    (select.closest('dialog') || document.body).append(panel);
    let rows = [], focused = -1, opened = false, search = '', typedAt = 0;
    const enabled = index => rows[index] && !rows[index].disabled;
    function sync() {
      caption.textContent = select.selectedOptions[0]?.label.trim() || '请选择';
      trigger.title = caption.textContent;
      const disabled = select.matches(':disabled');
      trigger.setAttribute('aria-disabled', String(disabled)); trigger.tabIndex = disabled ? -1 : 0;
      trigger.setAttribute('aria-required', String(select.required));
      trigger.dataset.placeholder = String(!select.value);
      if (select.validity.valid) { trigger.removeAttribute('aria-invalid'); error.hidden = true; }
      rows.forEach(row => row.el.setAttribute('aria-selected', String(row.option.selected)));
      if (disabled && opened) close();
    }
    function build() {
      panel.replaceChildren(); rows = [];
      for (const child of select.children) {
        let container = panel;
        if (child.tagName === 'OPTGROUP') {
          container = document.createElement('div'); container.setAttribute('role', 'group');
          container.setAttribute('aria-label', child.label);
          const heading = document.createElement('div'); heading.className = 'soft-select-group'; heading.textContent = child.label;
          heading.setAttribute('aria-hidden', 'true'); container.append(heading); panel.append(container);
        }
        const options = child.tagName === 'OPTGROUP' ? [...child.children] : [child];
        for (const option of options) {
          if (option.tagName !== 'OPTION' || option.hidden) continue;
          const el = document.createElement('div'), index = rows.length;
          const disabled = option.disabled || !!option.closest('optgroup')?.disabled;
          el.id = id + '-option-' + index; el.className = 'soft-select-option';
          el.setAttribute('role', 'option'); el.setAttribute('aria-disabled', String(disabled));
          el.textContent = option.label.trim(); el.dataset.index = index;
          container.append(el); rows.push({el, option, disabled});
        }
      }
      sync();
    }
    function focusOption(index) {
      if (!enabled(index)) return;
      focused = index;
      rows.forEach((row, i) => row.el.classList.toggle('is-active', i === focused));
      trigger.setAttribute('aria-activedescendant', rows[index].el.id);
      const row = rows[index].el;
      if (row.offsetTop < panel.scrollTop) panel.scrollTop = row.offsetTop;
      else if (row.offsetTop + row.offsetHeight > panel.scrollTop + panel.clientHeight) panel.scrollTop = row.offsetTop + row.offsetHeight - panel.clientHeight;
    }
    function position() {
      const rect = trigger.getBoundingClientRect();
      const viewport = window.visualViewport;
      const left = viewport?.offsetLeft || 0, top = viewport?.offsetTop || 0;
      const width = viewport?.width || innerWidth, height = viewport?.height || innerHeight;
      const below = top + height - rect.bottom - 16, above = rect.top - top - 16;
      const up = below < Math.min(panel.scrollHeight, 280) && above > below;
      panel.style.width = Math.min(Math.max(rect.width, 220), width - 24) + 'px';
      panel.style.maxHeight = Math.max(60, Math.min(340, up ? above : below)) + 'px';
      panel.style.left = Math.max(left + 12, Math.min(rect.left, left + width - panel.getBoundingClientRect().width - 12)) + 'px';
      panel.style.top = (up ? rect.top - panel.getBoundingClientRect().height - 7 : rect.bottom + 7) + 'px';
      panel.dataset.side = up ? 'top' : 'bottom';
    }
    function open() {
      sync(); if (select.matches(':disabled') || opened) return;
      active?.close(); build(); opened = true; active = api;
      panel.setAttribute('aria-hidden', 'false'); panel.inert = false;
      panel.classList.add('is-open');
      if (panel.showPopover) panel.showPopover();
      position(); trigger.setAttribute('aria-expanded', 'true');
      focused = rows.findIndex(row => row.option.selected && !row.disabled);
      if (focused < 0) focused = rows.findIndex(row => !row.disabled);
      focusOption(focused);
    }
    function close() {
      if (!opened) return;
      opened = false; if (active === api) active = null;
      trigger.setAttribute('aria-expanded', 'false'); trigger.removeAttribute('aria-activedescendant');
      panel.inert = true; panel.setAttribute('aria-hidden', 'true'); panel.classList.remove('is-open');
      if (panel.hidePopover && panel.matches(':popover-open')) panel.hidePopover();
      search = '';
    }
    function choose() {
      if (!enabled(focused)) { close(); return; }
      const next = rows[focused].option.index, changed = select.selectedIndex !== next;
      select.selectedIndex = next; sync(); close();
      if (changed) {
        select.dispatchEvent(new Event('input', {bubbles:true}));
        select.dispatchEvent(new Event('change', {bubbles:true}));
      }
    }
    const api = {close, trigger, panel}; instances.set(select, api);
    trigger.addEventListener('click', event => { event.preventDefault(); opened ? close() : open(); });
    panel.addEventListener('pointerdown', event => event.preventDefault());
    panel.addEventListener('click', event => {
      const row = event.target.closest('[data-index]'); if (!row || !enabled(+row.dataset.index)) return;
      focusOption(+row.dataset.index); trigger.focus({preventScroll:true}); choose();
    });
    trigger.addEventListener('keydown', event => {
      if (select.matches(':disabled')) return;
      if (event.key === 'Escape') { if (opened) {event.preventDefault(); event.stopPropagation(); close();} return; }
      if (event.key === 'Tab') { if (opened) choose(); return; }
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault(); opened ? choose() : open(); return;
      }
      if (['ArrowDown','ArrowUp','Home','End','PageDown','PageUp'].includes(event.key)) {
        event.preventDefault(); const wasOpen = opened; open();
        const available = rows.map((row,i)=>i).filter(enabled);
        let index = available.indexOf(focused);
        if (event.key === 'Home') index = 0;
        else if (event.key === 'End') index = available.length - 1;
        else if (wasOpen) index += (event.key.includes('Down') ? 1 : -1) * (event.key.startsWith('Page') ? 10 : 1);
        focusOption(available[Math.max(0, Math.min(available.length - 1, index))]); return;
      }
      if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
        event.preventDefault(); open();
        const now = performance.now(); search = now - typedAt > 700 ? event.key : search + event.key; typedAt = now;
        const query = [...search].every(char => char === search[0]) ? search[0] : search;
        const start = query.length === 1 ? focused + 1 : focused;
        for (let offset=0; offset<rows.length; offset++) {
          const index = (Math.max(0,start)+offset)%rows.length;
          if (enabled(index) && rows[index].el.textContent.toLocaleLowerCase().startsWith(query.toLocaleLowerCase())) {focusOption(index); break;}
        }
      }
    });
    trigger.addEventListener('blur', () => { if (opened) choose(); });
    select.addEventListener('focus', () => trigger.focus());
    select.addEventListener('change', sync); select.addEventListener('input', sync);
    select.addEventListener('invalid', event => {
      event.preventDefault(); trigger.setAttribute('aria-invalid', 'true');
      error.textContent = select.validationMessage; error.hidden = false;
      trigger.setAttribute('aria-describedby', [select.getAttribute('aria-describedby'),error.id].filter(Boolean).join(' '));
      // A form may contain several invalid selects; focus only the first invalid field.
      if (select.form?.querySelector('input:invalid,select:invalid,textarea:invalid') === select) trigger.focus();
    });
    select.form?.addEventListener('reset', () => setTimeout(() => {
      close(); sync(); trigger.removeAttribute('aria-invalid'); error.hidden = true;
    }, 0));
    new MutationObserver(() => { if (opened) {build(); position(); focusOption(rows.findIndex(row=>row.option.selected&&!row.disabled));} else sync(); })
      .observe(select, {childList:true, subtree:true, characterData:true, attributes:true, attributeFilter:['disabled','selected','label','required','hidden','value']});
    for (const fieldset of [...select.closest('form')?.querySelectorAll('fieldset') || []].filter(el => el.contains(select))) {
      new MutationObserver(sync).observe(fieldset, {attributes:true, attributeFilter:['disabled']});
    }
    sync();
  }
  function initFormControls() {
    if (!document.body.classList.contains('wb')) return;
    document.querySelectorAll('select').forEach(enhance);
    document.addEventListener('pointerdown', event => {
      if (active && !active.trigger.contains(event.target) && !active.panel.contains(event.target)) active.close();
    });
    addEventListener('resize', () => active?.close());
    window.visualViewport?.addEventListener('resize', () => active?.close());
    document.addEventListener('scroll', event => { if (active && !active.panel.contains(event.target)) active.close(); }, true);
    document.addEventListener('toggle', event => { if (event.target.tagName === 'DIALOG' && !event.target.open) active?.close(); }, true);
  }
  if (document.body) initFormControls();
  else document.addEventListener('DOMContentLoaded', initFormControls, {once:true});
})();
