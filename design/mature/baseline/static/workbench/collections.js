/* Reuse the real forms in native drawers. Moving nodes preserves validation and listeners. */
document.addEventListener('DOMContentLoaded', () => {
  if (!document.body.classList.contains('wb')) return;
  const search=new URLSearchParams(location.search);
  const hasFilters=['q','user','product_name','region_name','start_date','end_date','status','starred'].some(key=>search.has(key)&&search.get(key)&&search.get(key)!=='all');
  if(hasFilters)document.querySelectorAll('.empty-state,.empty-panel').forEach(empty=>{if(empty.closest('.table-wrap,.plaza-grid,.wb-panel,.wb-user-directory'))empty.textContent='没有符合当前筛选的记录。请调整筛选条件后再试。';});
  let sequence=0;
  function drawerFor(form,title,id) {
    const dialog=document.createElement('dialog');dialog.className='wb-drawer';dialog.id=id||`wb-editor-${++sequence}`;
    dialog.setAttribute('aria-labelledby',`${dialog.id}-title`);
    const header=document.createElement('header');header.className='wb-dialog-head';
    const heading=document.createElement('h2');heading.id=`${dialog.id}-title`;heading.textContent=title;
    const close=document.createElement('button');close.type='button';close.className='icon-btn';close.dataset.closeDrawer='';close.setAttribute('aria-label','关闭编辑');close.textContent='×';
    header.append(heading,close);const body=document.createElement('div');body.className='wb-dialog-body';
    form.classList.remove('hidden','top-gap','action-card');form.querySelector(':scope>h3')?.remove();body.append(form);dialog.append(header,body);document.body.append(dialog);return dialog;
  }
  document.querySelectorAll('[data-create-editor]').forEach(form=>{
    const title=form.dataset.createEditor;
    const trigger=document.createElement('button');trigger.type='button';trigger.className='primary-btn wb-create-launch';trigger.textContent=title;
    form.before(trigger);trigger.dataset.openDrawer=drawerFor(form,title).id;
    document.querySelector('.wb-page-heading')?.append(trigger);
  });
  document.querySelectorAll('[data-toggle-edit]').forEach(trigger=>{
    const target=document.getElementById(trigger.dataset.toggleEdit);if(!target)return;
    const form=target.matches('form')?target:target.querySelector('form');if(!form)return;
    trigger.removeAttribute('data-toggle-edit');trigger.dataset.openDrawer=drawerFor(form,'编辑配置').id;
    if(target!==form)target.remove();
  });
  document.querySelectorAll('details.row-editor').forEach(details=>{
    const form=details.querySelector('form');if(!form)return;
    const trigger=document.createElement('button');trigger.type='button';trigger.className='ghost-btn small-btn';trigger.textContent=details.querySelector('summary')?.textContent||'编辑';
    const dialog=drawerFor(form,trigger.textContent);trigger.dataset.openDrawer=dialog.id;details.replaceWith(trigger);
  });
  document.querySelectorAll('form[data-short-editor]').forEach(form=>{
    const title=form.querySelector('h3')?.textContent||'编辑';const row=document.createElement('div');row.className='wb-editor-launch';
    const label=document.createElement('span');label.textContent=title;const trigger=document.createElement('button');trigger.type='button';trigger.className='secondary-btn';trigger.textContent='编辑';
    form.before(row);row.append(label,trigger);trigger.dataset.openDrawer=drawerFor(form,title).id;
  });
  document.querySelectorAll('.table-wrap').forEach(wrap=>{wrap.tabIndex=0;wrap.setAttribute('role','region');wrap.setAttribute('aria-label','数据表格，可横向滚动');});
  document.querySelectorAll('.task-tabs-card,.wb-detail-tabs').forEach(card=>{
    const buttons=[...card.querySelectorAll('.tab-button[data-tab-target]')];card.querySelector('.tab-nav')?.setAttribute('role','tablist');
    function sync(){buttons.forEach(button=>{const selected=button.classList.contains('active');button.setAttribute('role','tab');button.setAttribute('aria-selected',String(selected));button.tabIndex=selected?0:-1;const panel=card.querySelector(`[data-tab-panel="${button.dataset.tabTarget}"]`);if(panel){panel.id||=`panel-${button.dataset.tabTarget}`;button.id||=`tab-${button.dataset.tabTarget}`;button.setAttribute('aria-controls',panel.id);panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby',button.id);}});}
    buttons.forEach((button,index)=>{button.addEventListener('click',sync);button.addEventListener('keydown',event=>{let next;if(event.key==='ArrowRight')next=(index+1)%buttons.length;else if(event.key==='ArrowLeft')next=(index-1+buttons.length)%buttons.length;else if(event.key==='Home')next=0;else if(event.key==='End')next=buttons.length-1;else return;event.preventDefault();buttons[next].click();buttons[next].focus();});});sync();
  });
  document.querySelectorAll('.settings-form').forEach(form=>form.addEventListener('invalid',event=>{
    const panel=event.target.closest('[data-tab-panel]');if(panel&&!panel.classList.contains('active'))form.querySelector(`[data-tab-target="${panel.dataset.tabPanel}"]`)?.click();
  },true));
});
