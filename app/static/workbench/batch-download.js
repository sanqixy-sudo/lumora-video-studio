(() => {
  const all=document.getElementById('batch-select-all'),clear=document.getElementById('batch-clear-selection'),download=document.getElementById('batch-bulk-download');
  if (!all || !download) return;
  const available=[...document.querySelectorAll('.batch-select-checkbox:not(:disabled)')];
  const count=document.getElementById('batch-selection-count'),status=document.getElementById('batch-download-status'),error=document.getElementById('batch-download-error');
  let busy=false;
  const selected=()=>available.filter(box=>box.checked);
  function sync(){
    const chosen=selected();all.checked=available.length>0&&chosen.length===available.length;all.indeterminate=chosen.length>0&&chosen.length<available.length;
    all.disabled=busy||!available.length;clear.disabled=busy||!chosen.length;download.disabled=busy||!chosen.length;
    count.textContent=`已选 ${chosen.length} 个批次 · ${chosen.reduce((n,b)=>n+Number(b.dataset.videos),0)} 个视频`;
  }
  function showError(message){error.textContent=message;error.classList.remove('hidden');}
  available.forEach(box=>box.addEventListener('change',()=>{error.classList.add('hidden');if(selected().length>20){box.checked=false;showError('一次最多选择 20 个批次。');}sync();}));
  all.addEventListener('change',()=>{const checked=all.checked;available.forEach((box,i)=>box.checked=checked&&i<20);error.classList.add('hidden');if(checked&&available.length>20)status.textContent='已选择当前页前 20 个可下载批次。';sync();});
  clear.addEventListener('click',()=>{available.forEach(box=>box.checked=false);error.classList.add('hidden');status.textContent='';sync();});
  download.addEventListener('click',()=>{
    if(busy||!selected().length)return;
    busy=true;error.classList.add('hidden');status.textContent='正在打包，请稍候…';download.textContent='正在打包…';download.setAttribute('aria-busy','true');available.forEach(box=>box.disabled=true);sync();
    const token=[...crypto.getRandomValues(new Uint8Array(16))].map(v=>v.toString(16).padStart(2,'0')).join('');
    const cookie='batch_zip_'+token,frame=document.createElement('iframe');frame.hidden=true;frame.title='批次 ZIP 下载';
    let done=false,timer,timeout;
    const clearCookie=()=>{document.cookie=`${cookie}=; Max-Age=0; Path=/app/job-batches; SameSite=Strict`;};
    function finish(message,failed=false){
      if(done)return;done=true;clearInterval(timer);clearTimeout(timeout);clearCookie();busy=false;available.forEach(box=>box.disabled=false);download.textContent='下载选中批次 ZIP';download.removeAttribute('aria-busy');sync();
      status.textContent=failed?'':message;if(failed){showError(message);frame.remove();}
    }
    frame.addEventListener('load',()=>{
      if(done)return;
      try{
        if(new URL(frame.contentWindow.location.href).pathname==='/login'){finish('登录已过期，请刷新页面后重新登录。',true);return;}
        const text=frame.contentDocument?.body?.textContent?.trim();if(!text)return;
        let detail;try{detail=JSON.parse(text).detail;}catch(_){}
        finish(typeof detail==='string'?detail:'下载未能启动，请刷新页面后重试。',true);
      }catch(_){finish('下载未能启动，请刷新页面后重试。',true);}
    });
    const ids=selected().map(box=>box.value).join(',');
    frame.src=`/app/job-batches/bulk-download?batch_ids=${encodeURIComponent(ids)}&download_token=${token}`;document.body.appendChild(frame);
    timer=setInterval(()=>{
      const value=document.cookie.split('; ').find(item=>item.startsWith(cookie+'='))?.split('=')[1];
      if(value==='ready')finish('压缩包已准备好，浏览器已开始下载。');
    },400);
    timeout=setTimeout(()=>finish('打包等待时间较长，请先检查浏览器下载列表；如未开始下载，请减少所选批次后重试。',true),300000);
  });
  sync();
})();
