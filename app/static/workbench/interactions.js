/* Interaction layer for the new workbench; existing submission protocols are reused. */
(() => {
  const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
  const enter = 'cubic-bezier(.22,1,.36,1)';
  function reveal(element,duration=140,distance=6) {
    window.SoraWorkbenchMotion?.reveal(element,duration,distance);
  }
  let activeDialog = null;
  const origins = new WeakMap();
  function openDialog(dialog, trigger) {
    if (!dialog || dialog.open) return;
    if (activeDialog?.open) closeDialog(activeDialog);
    origins.set(dialog,trigger || document.activeElement);
    dialog.showModal(); activeDialog=dialog;
    dialog.querySelector(matchMedia('(min-width:768px)').matches?'input:not([type=hidden]),button':'button,a[href]')?.focus({preventScroll:true});
  }
  function closeDialog(dialog) {
    if (!dialog?.open) return;
    dialog.close(); if(activeDialog===dialog) activeDialog=null;
    origins.get(dialog)?.focus({preventScroll:true});
  }
  document.addEventListener('DOMContentLoaded', () => {
    if (!document.body.classList.contains('wb')) return;
    document.addEventListener('keydown',event=>{
      if(event.key!=='Tab')return;
      const dialog=document.querySelector('dialog[open]');if(!dialog)return;
      const controls=[...dialog.querySelectorAll('button,a[href],input:not([type=hidden]),select,textarea,[tabindex="0"]')].filter(el=>!el.disabled&&el.getClientRects().length);
      if(!controls.length){event.preventDefault();return;}
      const first=controls[0],last=controls[controls.length-1];
      if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
      else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
    });
    document.querySelectorAll('.wb-drawer').forEach(dialog => {
      dialog.addEventListener('cancel', event => {event.preventDefault();closeDialog(dialog);});
      dialog.addEventListener('click', event => {if(event.target===dialog && event.clientX<dialog.getBoundingClientRect().left) closeDialog(dialog);});
    });
    document.addEventListener('click', event => {
      const opener=event.target.closest('[data-open-drawer]');
      if(opener) openDialog(document.getElementById(opener.dataset.openDrawer),opener);
      const closer=event.target.closest('[data-close-drawer]');
      if(closer) closeDialog(closer.closest('dialog'));
    });

    document.querySelectorAll('[data-theme-select]').forEach(select=>select.addEventListener('change',()=>{
      document.documentElement.setAttribute('data-theme-switching','');
      requestAnimationFrame(()=>requestAnimationFrame(()=>document.documentElement.removeAttribute('data-theme-switching')));
    },true));

    // Navigation settles its layout once, then animates painted positions. Mobile uses a native modal.
    try {document.body.classList.toggle('wb-nav-collapsed',localStorage.getItem('sora.nav.collapsed')==='true');} catch(_) {}
    const collapse=document.querySelector('[data-collapse-nav]');
    function updateCollapse(){const collapsed=document.body.classList.contains('wb-nav-collapsed');collapse?.setAttribute('aria-expanded',String(!collapsed));if(collapse)collapse.title=collapsed?'展开导航':'收起导航';}
    updateCollapse();
    collapse?.addEventListener('click',()=>{const change=()=>{document.body.classList.toggle('wb-nav-collapsed');updateCollapse();};if(window.SoraWorkbenchMotion)SoraWorkbenchMotion.navigation(change);else change();try{localStorage.setItem('sora.nav.collapsed',String(document.body.classList.contains('wb-nav-collapsed')));}catch(_) {}});
    const mobileTrigger=document.querySelector('[data-open-nav]'),sidebar=document.querySelector('.wb-sidebar');
    if(mobileTrigger&&sidebar){
      const slot=document.createComment('navigation');sidebar.before(slot);
      const dialog=document.createElement('dialog');dialog.className='wb-mobile-nav-dialog';dialog.setAttribute('aria-label','主导航');document.body.append(dialog);
      let navExitTimer;
      function finishNav(){clearTimeout(navExitTimer);slot.after(sidebar);}
      function closeNav(){closeDialog(dialog);mobileTrigger.setAttribute('aria-expanded','false');clearTimeout(navExitTimer);if(reduced()||innerWidth>=768)finishNav();else navExitTimer=setTimeout(finishNav,200);}
      mobileTrigger.addEventListener('click',()=>{clearTimeout(navExitTimer);dialog.append(sidebar);openDialog(dialog,mobileTrigger);mobileTrigger.setAttribute('aria-expanded','true');});
      dialog.addEventListener('cancel',e=>{e.preventDefault();closeNav();});
      dialog.addEventListener('click',e=>{if(e.target===dialog)closeNav();});
      matchMedia('(min-width:768px)').addEventListener('change',e=>{if(e.matches){if(dialog.open)closeNav();else finishNav();}});
    }
    const account=document.querySelector('[data-account-toggle]'),accountMenu=document.getElementById('wb-account-menu');
    function closeAccount(restore=false){if(!accountMenu)return;accountMenu.classList.add('hidden');accountMenu.inert=true;account?.setAttribute('aria-expanded','false');if(restore)account?.focus();}
    account?.addEventListener('click',()=>{const open=accountMenu.classList.contains('hidden');accountMenu.classList.toggle('hidden',!open);accountMenu.inert=!open;account.setAttribute('aria-expanded',String(open));});
    document.addEventListener('click',e=>{if(!e.target.closest('.wb-account'))closeAccount();});
    document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!accountMenu?.classList.contains('hidden'))closeAccount(true);});
    document.addEventListener('focusin',e=>{if(accountMenu&&!e.target.closest('.wb-account'))closeAccount();});

    // Portal each real menu once. Keep its viewport position through the closing fade.
    let rowMenu=null,rowOrigin=null;
    function closeRow(restore=false){
      if(!rowMenu)return;
      const origin=rowOrigin;rowMenu.classList.remove('wb-menu-open');rowMenu.classList.add('hidden');rowMenu.inert=true;rowMenu.setAttribute('aria-hidden','true');origin.setAttribute('aria-expanded','false');rowMenu=null;
      if(restore)origin.focus({preventScroll:true});
    }
    document.querySelectorAll('.wb-row-trigger').forEach((trigger,index)=>{
      const panel=trigger.parentElement.querySelector('.menu-panel');if(!panel)return;
      panel.id||=`wb-row-menu-${index}`;panel.setAttribute('role','region');panel.setAttribute('aria-label',`记录操作 ${index+1}`);trigger.setAttribute('aria-controls',panel.id);trigger.setAttribute('aria-expanded','false');
      trigger.addEventListener('click',()=>{
        if(rowOrigin===trigger&&rowMenu){closeRow();return;}closeRow();
        rowOrigin=trigger;rowMenu=panel;document.body.append(panel);panel.classList.add('wb-floating-menu','wb-menu-open');panel.classList.remove('hidden');panel.inert=false;panel.removeAttribute('aria-hidden');trigger.setAttribute('aria-expanded','true');
        const rect=trigger.getBoundingClientRect();panel.style.right=`${Math.max(12,innerWidth-rect.right)}px`;
        const height=panel.getBoundingClientRect().height;panel.style.top=`${Math.max(8,Math.min(rect.bottom+6,innerHeight-height-12))}px`;
        panel.querySelector('a,button')?.focus({preventScroll:true});
      });
    });
    document.addEventListener('click',e=>{if(!e.target.closest('.wb-row-trigger,.wb-menu-open'))closeRow();});
    document.addEventListener('keydown',e=>{if(!rowMenu)return;if(e.key==='Escape'){e.preventDefault();closeRow(true);}else if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();const items=[...rowMenu.querySelectorAll('a,button')];const i=items.indexOf(document.activeElement);items[(i+(e.key==='ArrowDown'?1:-1)+items.length)%items.length]?.focus();}});
    document.addEventListener('focusin',e=>{if(rowMenu&&!rowMenu.contains(e.target)&&e.target!==rowOrigin)closeRow();});
    addEventListener('resize',()=>closeRow());
    document.querySelectorAll('.table-wrap').forEach(wrap=>wrap.addEventListener('scroll',()=>closeRow()));

    const model=document.getElementById('job-model-select'),drawer=document.getElementById('wb-material-drawer');
    if(model&&drawer){
      const originals=[...document.querySelectorAll('[name=omni_reference_preset_ids]')];
      const standard=document.getElementById('reference-preset-select');
      const presetGrid=drawer.querySelector('.wb-preset-grid');
      const nameOrder=new Intl.Collator('zh-CN',{numeric:true,sensitivity:'base'});
      const presetCards=[...presetGrid.querySelectorAll('.wb-preset-choice')];
      presetCards.sort((a,b)=>nameOrder.compare(a.querySelector('strong').textContent.trim(),b.querySelector('strong').textContent.trim()));
      presetGrid.append(...presetCards);
      const choices=[...drawer.querySelectorAll('[data-preset-choice]')];
      const selected=document.getElementById('wb-selected-materials');
      let draft=new Set();
      const provider=()=>model.selectedOptions[0]?.dataset.provider||'';
      const isOmni=()=>['veo_omni','wuyin_omni'].includes(provider());
      const maximum=()=>provider()==='veo_omni'?6:1;
      const urlCount=()=>isOmni()?[...document.querySelectorAll('[name=omni_reference_image_urls]')].filter(el=>el.value.trim()).length:0;
      function renderDraft(){
        const available=Math.max(0,maximum()-urlCount());
        choices.forEach(choice=>{choice.checked=draft.has(choice.value);choice.disabled=!choice.checked&&draft.size>=available&&maximum()>1 || available===0;});
        document.getElementById('wb-material-draft-count').textContent=`已选择 ${draft.size} 张`;
        document.getElementById('wb-material-limit').textContent=`${isOmni()?provider()==='veo_omni'?'VEO Omni':'Wuyin Omni':'当前模型'} · 最多 ${maximum()} 张${urlCount()?`，已有 ${urlCount()} 个图片链接`:''}`;
      }
      function renderSelected(){
        selected.replaceChildren();
        const chosen=isOmni()?originals.filter(el=>el.checked):originals.filter(el=>el.value===standard.value);
        chosen.forEach(item=>{
          const row=document.createElement('div');row.className='wb-selected-item';
          const image=document.createElement('img');image.width=Number(item.dataset.width)||720;image.height=Number(item.dataset.height)||1280;image.src=item.dataset.url;image.alt=item.dataset.name;image.referrerPolicy='no-referrer';
          const text=document.createElement('span'),name=document.createElement('strong'),size=document.createElement('small');name.textContent=item.dataset.name;size.textContent=`${item.dataset.width} × ${item.dataset.height}`;text.append(name,size);
          const remove=document.createElement('button');remove.type='button';remove.textContent='×';remove.setAttribute('aria-label',`移除 ${item.dataset.name}`);
          remove.onclick=()=>{if(isOmni()){item.checked=false;item.dispatchEvent(new Event('change',{bubbles:true}));}else{standard.value='';standard.dispatchEvent(new Event('change',{bubbles:true}));}renderSelected();};row.append(image,text,remove);selected.append(row);
        });
      }
      document.querySelector('[data-open-materials]').addEventListener('click',e=>{
        draft=new Set(isOmni()?originals.filter(el=>el.checked).map(el=>el.value):standard.value?[standard.value]:[]);renderDraft();openDialog(drawer,e.currentTarget);
      });
      choices.forEach(choice=>choice.addEventListener('change',()=>{if(choice.checked){if(maximum()===1)draft.clear();draft.add(choice.value);}else draft.delete(choice.value);renderDraft();}));
      document.getElementById('wb-apply-materials').addEventListener('click',()=>{
        if(draft.size+urlCount()>maximum())return;
        if(isOmni()){originals.forEach(el=>{el.checked=draft.has(el.value);});originals.forEach(el=>el.dispatchEvent(new Event('change',{bubbles:true})));}
        else{standard.value=[...draft][0]||'';document.getElementById('reference-image-url').value='';standard.dispatchEvent(new Event('change',{bubbles:true}));}
        renderSelected();closeDialog(drawer);
      });
      model.addEventListener('change',()=>{if(drawer.open)closeDialog(drawer);renderSelected();});
      document.querySelector('#create-job-form').addEventListener('change',e=>{if(e.target===standard||originals.includes(e.target))renderSelected();});
      renderSelected();
    }
    const prompts=document.getElementById('prompt-list');
    if(prompts){
      function updatePrompts(){const count=prompts.querySelectorAll('[data-prompt-card]').length;document.getElementById('wb-prompt-total').textContent=count;prompts.querySelectorAll('textarea').forEach((el,i)=>{el.setAttribute('aria-label',`提示词 ${i+1}`);});}
      new MutationObserver(records=>{const added=records.flatMap(r=>[...r.addedNodes]).filter(n=>n.nodeType===1&&n.matches('[data-prompt-card]'));if(added.length===1)reveal(added[0]);updatePrompts();}).observe(prompts,{childList:true});updatePrompts();
      // Restore a useful focus position after removing a prompt.
      prompts.addEventListener('click',e=>{const remove=e.target.closest('[data-remove-prompt]');if(!remove)return;const card=remove.closest('[data-prompt-card]'),next=card.nextElementSibling||card.previousElementSibling;if(next)queueMicrotask(()=>next.querySelector('textarea')?.focus({preventScroll:true}));},true);
      const text=document.getElementById('batch-import-textarea');text?.addEventListener('input',()=>{const count=text.value.split(/\n\s*---\s*\n|\n\s*\n/g).map(s=>s.trim()).filter(Boolean).length;document.getElementById('wb-import-count').textContent=`已解析 ${count} 条${count>100?'，超过 100 条上限':''}`;});
    }
    document.querySelector('[data-copy-remote-id]')?.addEventListener('click',async e=>{const button=e.currentTarget;const value=document.getElementById('job-remote').textContent;if(!value.trim()||value.trim()==='-'){SoraUI.toast('暂无远端任务编号。','error');return;}if(await copyTextToClipboard(value))SoraUI.feedback(button,'已复制');else SoraUI.toast('复制失败，请选择编号后手动复制。','error');});
    document.querySelectorAll('.tab-button').forEach(button=>button.addEventListener('click',()=>reveal((button.closest('.task-tabs-card,.wb-detail-tabs')||document).querySelector('.tab-panel.active'),120,0)));
    if(document.body.classList.contains('wb-auth-page')){
      let first=true;try{first=!sessionStorage.getItem('sora.studio.intro');sessionStorage.setItem('sora.studio.intro','1');}catch(_){}
      if(first)reveal(document.querySelector('.wb-cinema'),650,12);
      document.querySelectorAll('[data-show-login],[data-show-register]').forEach(button=>button.addEventListener('click',()=>{const register=button.hasAttribute('data-show-register');const form=document.querySelector(register?'[data-register-form]':'[data-login-form]');reveal(form,160);if(innerWidth>=768)form?.querySelector('input:not([type=hidden])')?.focus({preventScroll:true});else{const title=document.getElementById('login-panel-title');title.tabIndex=-1;title.focus({preventScroll:true});}if(!register){document.getElementById('login-panel-title').textContent='欢迎回来';document.getElementById('login-panel-subtitle').textContent='登录流光，继续你的创作。';}}));
    }
  });
})();
