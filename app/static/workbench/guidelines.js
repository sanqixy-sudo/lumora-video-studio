/* Progressive enhancements; no stored drafts or changes to submission payloads. */
document.addEventListener('DOMContentLoaded',()=>{
  const body=document.body;
  if(!body.classList.contains('wb'))return;
  document.querySelectorAll('.table-wrap').forEach((wrap,index)=>{
    const section=wrap.closest('section,.tab-panel');
    const title=section?.querySelector('h2,h3')?.textContent.trim()||document.querySelector('.wb-location h1')?.textContent||'数据';
    wrap.setAttribute('aria-label',`${title}，表格 ${index+1}，可横向滚动`);
  });
  document.querySelectorAll('[role=status]').forEach(el=>el.setAttribute('aria-live','polite'));
  document.querySelectorAll('.lumora-logo,.wb-brand,.wb-auth-brand,.mono-cell,.mono-line,code,.card-model-id').forEach(el=>el.setAttribute('translate','no'));
  document.querySelectorAll('input[name=username],input[name=raw_key],input[name^=model_id],input[type=url]').forEach(el=>el.spellcheck=false);
  const prompts=document.getElementById('prompt-list');
  const large=element=>element.classList.toggle('wb-large-list',element.children.length>50);
  document.querySelectorAll('.table tbody').forEach(large);
  if(prompts){
    large(prompts);new MutationObserver(()=>large(prompts)).observe(prompts,{childList:true});
    // Deferred cards resolve their real height after focus; correct native scrolling once.
    let focusFrame=0;
    prompts.addEventListener('focusin',event=>{
      cancelAnimationFrame(focusFrame);
      const target=event.target;
      focusFrame=requestAnimationFrame(()=>{
        if(document.activeElement===target&&target.isConnected)
          target.scrollIntoView({block:'nearest',inline:'nearest',behavior:'instant'});
      });
    });
  }
  // Keep browser navigation protection only for actual editing; never persist credentials or drafts.
  const dirty=new Set();
  function editableForm(el){const form=el.closest('form');return form&&form.method.toLowerCase()==='post'&&!form.matches('[data-login-form],[data-register-form]')?form:null;}
  document.addEventListener('input',event=>{const form=editableForm(event.target);if(form)dirty.add(form);});
  document.addEventListener('change',event=>{const form=editableForm(event.target);if(form&&!event.target.matches('[data-theme-select]'))dirty.add(form);});
  document.addEventListener('lumora:saved',event=>{if(event.detail?.form)dirty.delete(event.detail.form);else dirty.clear();});
  document.addEventListener('reset',event=>dirty.delete(event.target));
  addEventListener('beforeunload',event=>{if(!dirty.size)return;event.preventDefault();event.returnValue='';});
  // Native validation selects the relevant settings tab before focusing its invalid field.
  document.querySelectorAll('form').forEach(form=>form.addEventListener('invalid',event=>{
    const first=form.querySelector(':invalid');if(first===event.target)queueMicrotask(()=>first.focus({preventScroll:false}));
  },true));
});

// Only presentation is localized. The application and its logs retain Asia/Shanghai semantics.
(() => {
  const locale=document.documentElement.lang||navigator.languages?.[0]||'zh-CN';
  const number=new Intl.NumberFormat(locale);
  const dates=new Map();
  function dateText(raw){
    const match=String(raw).trim().match(/^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})(:\d{2})?$/);
    if(!match)return raw;
    const value=new Date(`${match[1]}T${match[2]}${match[3]||':00'}+08:00`);
    if(Number.isNaN(value.getTime()))return raw;
    const seconds=!!match[3];
    if(!dates.has(seconds))dates.set(seconds,new Intl.DateTimeFormat(locale,{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',...(seconds?{second:'2-digit'}:{}),hourCycle:'h23'}));
    return dates.get(seconds).format(value);
  }
  window.LumoraFormat={time:dateText,number:value=>number.format(value)};
  document.addEventListener('DOMContentLoaded',()=>{
    function formatTime(el){const raw=el.textContent.trim();if(!/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}(:\d{2})?$/.test(raw))return;el.dateTime=raw.replace(' ','T')+(raw.length===16?':00':'')+'+08:00';el.textContent=dateText(raw);el.title='北京时间（Asia/Shanghai）';}
    document.querySelectorAll('time').forEach(formatTime);
    const counters=document.querySelectorAll('.metric-card strong,.batch-stat strong,.wb-count');
    function formatNumber(el){if(/^-?\d+(\.\d+)?$/.test(el.textContent.trim())){const raw=el.textContent.trim(),formatted=number.format(Number(raw));if(raw!==formatted)el.textContent=formatted;}}
    counters.forEach(el=>{formatNumber(el);new MutationObserver(()=>formatNumber(el)).observe(el,{childList:true,characterData:true,subtree:true});});
    // Reading panels are shareable; temporary selection drawers are deliberately not URL state.
    const panels=[...document.querySelectorAll('details:not(.row-editor)')];
    panels.forEach((panel,index)=>{panel.dataset.panelKey=panel.id||`reading-${index+1}`;});
    const parameter='panels';let restoring=false;
    function restore(){restoring=true;const selected=new URL(location.href).searchParams.get(parameter);if(selected!==null){const keys=new Set(selected.split(','));panels.forEach(panel=>panel.open=keys.has(panel.dataset.panelKey));}queueMicrotask(()=>restoring=false);}
    restore();
    panels.forEach(panel=>panel.addEventListener('toggle',()=>{if(restoring)return;const url=new URL(location.href);const keys=panels.filter(item=>item.open).map(item=>item.dataset.panelKey);url.searchParams.set(parameter,keys.join(','));history.replaceState(history.state,'',url);}));
    addEventListener('popstate',restore);
  });
})();
