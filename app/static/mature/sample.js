/* Only editor presentation changes. Existing submission and validation own data. */
document.addEventListener('DOMContentLoaded',()=>{
  const list=document.getElementById('prompt-list');
  if(list){
    const paths={copy:'<path stroke-linecap="round" stroke-linejoin="round" d="M9 9V5.25A2.25 2.25 0 0 1 11.25 3h7.5A2.25 2.25 0 0 1 21 5.25v7.5A2.25 2.25 0 0 1 18.75 15H15M5.25 9h7.5A2.25 2.25 0 0 1 15 11.25v7.5A2.25 2.25 0 0 1 12.75 21h-7.5A2.25 2.25 0 0 1 3 18.75v-7.5A2.25 2.25 0 0 1 5.25 9Z"/>',remove:'<path stroke-linecap="round" stroke-linejoin="round" d="m6 6 12 12M6 18 18 6"/>',collapse:'<path stroke-linecap="round" stroke-linejoin="round" d="m6 15 6-6 6 6"/>'};
    function decorate(){list.querySelectorAll('[data-prompt-card]').forEach((card,index)=>{
      const heading=card.querySelector('.prompt-card-head strong');heading.dataset.promptNumber=String(index+1).padStart(2,'0');heading.setAttribute('aria-label',`提示词 ${index+1}`);
      let button=card.querySelector('[data-collapse-prompt]');
      if(!button){button=document.createElement('button');button.type='button';button.className='ghost-btn small-btn';button.dataset.collapsePrompt='';card.querySelector('.prompt-card-head .inline-actions').prepend(button);}
      for(const [key,selector,label] of [['collapse','[data-collapse-prompt]','收起此提示词编辑区'],['copy','[data-copy-prompt]','复制提示词'],['remove','[data-remove-prompt]','删除提示词']]){
        const control=card.querySelector(selector);control.setAttribute('aria-label',label);control.title=label;
        if(!control.dataset.glassIcon){control.innerHTML=`<svg class="wb-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">${paths[key]}</svg>`;control.dataset.glassIcon=key;}
      }
    });}
    decorate();new MutationObserver(decorate).observe(list,{childList:true});
    list.addEventListener('focusin',event=>{if(event.target.matches('textarea'))event.target.closest('[data-prompt-card]').classList.add('is-expanded');});
    list.addEventListener('click',event=>{const button=event.target.closest('[data-collapse-prompt]');if(!button)return;const card=button.closest('[data-prompt-card]');card.classList.remove('is-expanded');card.querySelector('textarea').style.height='';card.querySelector('[data-copy-prompt]').focus({preventScroll:true});});
  }
  // The artwork is static after one per-tab introduction, separate from login form availability.
  const art=document.querySelector('.mature-storyboards');
  let first=true;try{first=!sessionStorage.getItem('lumora.mature.intro');sessionStorage.setItem('lumora.mature.intro','1');}catch(_){}
  if(art&&first&&!matchMedia('(prefers-reduced-motion:reduce)').matches){const animation=art.animate([{opacity:0,transform:'translateY(12px)'},{opacity:1,transform:'translateY(0)'}],{duration:650,easing:'cubic-bezier(.22,1,.36,1)'});matchMedia('(prefers-reduced-motion:reduce)').addEventListener('change',event=>{if(event.matches)animation.cancel();},{once:true});}
});
