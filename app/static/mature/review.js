/* Local design review only. Frames use actual templates and mock responses. */
const routes={login:'/login',create:'/app',detail:'/app/jobs/101/page?state=completed',users:'/admin/users/page',usage:'/admin/usage/monthly/page'};
const params=new URLSearchParams(location.search),theme=document.querySelector('#theme'),scenario=document.querySelector('#scenario'),before=document.querySelector('#old'),after=document.querySelector('#new'),error=document.querySelector('#review-error');
let current=Object.hasOwn(routes,params.get('page'))?params.get('page'):'create',generation=0;
try{theme.value=localStorage.getItem('sora.theme')||'light';}catch(_){}
function route(){return current==='detail'?'/app/jobs/101/page'+document.querySelector('#detail-state').value:routes[current];}
function apply(frame){try{frame.contentDocument.querySelectorAll('[data-theme-select]').forEach(s=>{s.value=theme.value;s.dispatchEvent(new Event('change',{bubbles:true}));});}catch(_) {}}
function example(frame){
 if(current!=='create')return;
 const d=frame.contentDocument,model=d.querySelector('#job-model-select');if(!model)return;
 const option=[...model.options].find(o=>o.dataset.provider==='veo_omni');if(!option)return;
 model.value=option.value;model.dispatchEvent(new Event('change',{bubbles:true}));
 for(const [name,value] of Object.entries({product_name:'Lumora Studio',region_name:'美国',batch_name:'镜头探索'})){const e=d.querySelector('[name='+name+']');e.value=value;e.dispatchEvent(new Event('input',{bubbles:true}));}
 const prompts=['雨夜城市，镜头缓慢推进。湿润的路面映出暖色灯光，路人撑伞经过，保持自然景深。','以产品为视觉中心。柔和的侧光掠过玻璃，镜头从轮廓移动到细节，背景安静、干净。','自然光下的人物侧影，镜头缓缓拉远，保留环境与人物之间的呼吸感。'];
 while(d.querySelectorAll('#prompt-list textarea').length<prompts.length)d.querySelector('#add-prompt-btn').click();
 d.querySelectorAll('#prompt-list textarea').forEach((e,i)=>{e.value=prompts[i]||'';e.dispatchEvent(new Event('input',{bubbles:true}));e.closest('.prompt-card').classList.remove('is-expanded');});
 const choice=d.querySelector('[data-preset-choice]'),selected=choice&&d.querySelector('[name=omni_reference_preset_ids][value="'+choice.value+'"]');if(selected){selected.checked=true;selected.dispatchEvent(new Event('change',{bubbles:true}));}
 d.activeElement?.blur();frame.contentWindow.scrollTo(0,0);
}
async function load(){
 const token=++generation;error.hidden=true;document.querySelectorAll('[data-review-page]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.reviewPage===current)));document.querySelector('#detail-options').hidden=current!=='detail';
 try{localStorage.setItem('sora.theme',theme.value);}catch(_){}
 const locationURL=new URL(location.href);locationURL.searchParams.set('page',current);locationURL.searchParams.set('revision','glass-2');history.replaceState(null,'',locationURL);
 let url=route();if(scenario.value)url+=(url.includes('?')?'&':'?')+(scenario.value==='empty'?'state=empty':'scenario=error');document.querySelector('#direct').href=url;document.querySelector('#new-label').textContent=document.querySelector('[data-review-page="'+current+'"]').textContent+' · glass-2';
 try{const response=await fetch(url,{cache:'no-store',signal:AbortSignal.timeout(5000)});if(!response.ok)throw new Error('preview unavailable');if(token!==generation)return;after.src=url;if(document.body.classList.contains('compare'))before.src='/before'+route();}
 catch(_){if(token!==generation)return;error.hidden=false;}
}
before.onload=()=>apply(before);after.onload=()=>{apply(after);example(after);};
document.querySelectorAll('[data-review-page]').forEach(b=>b.addEventListener('click',()=>{current=b.dataset.reviewPage;scenario.value='';load();}));
scenario.onchange=document.querySelector('#detail-state').onchange=load;
theme.onchange=()=>{try{localStorage.setItem('sora.theme',theme.value);}catch(_){}apply(before);apply(after);};
document.querySelector('#compare').onclick=e=>{const active=document.body.classList.toggle('compare');e.currentTarget.setAttribute('aria-pressed',String(active));if(active)before.src='/before'+route();};
document.querySelector('#phone').onclick=e=>{const active=document.body.classList.toggle('phone');e.currentTarget.setAttribute('aria-pressed',String(active));};
document.querySelector('#retry-preview').onclick=load;
load();
