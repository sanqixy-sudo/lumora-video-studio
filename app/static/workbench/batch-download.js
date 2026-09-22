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
  function startDownload(id){
    return new Promise(resolve=>{
      const token=[...crypto.getRandomValues(new Uint8Array(16))].map(v=>v.toString(16).padStart(2,'0')).join('');
      const cookie='batch_zip_'+token,frame=document.createElement('iframe');frame.hidden=true;frame.title=`批次 ${id} ZIP 下载`;
      let done=false,timer,timeout;
      function finish(message='',stop=false){
        if(done)return;done=true;clearInterval(timer);clearTimeout(timeout);
        document.cookie=`${cookie}=; Max-Age=0; Path=/app/job-batches; SameSite=Strict`;
        // Keep attachment frames alive so the browser can finish transferring them.
        if(message)frame.remove();
        resolve({message,stop});
      }
      frame.addEventListener('load',()=>{
        if(done)return;
        try{
          const location=new URL(frame.contentWindow.location.href);
          if(location.href==='about:blank')return;
          if(location.pathname==='/login'){finish('登录已过期，请刷新页面后重新登录。',true);return;}
          const text=frame.contentDocument?.body?.textContent?.trim();if(!text)return;
          let detail;try{detail=JSON.parse(text).detail;}catch(_){}
          finish(typeof detail==='string'?detail:'下载未能启动，请稍后重试。');
        }catch(_){finish('下载未能启动，请刷新页面后重试。',true);}
      });
      frame.src=`/app/job-batches/${encodeURIComponent(id)}/download-zip?download_token=${token}`;
      timer=setInterval(()=>{
        const value=document.cookie.split('; ').find(item=>item.startsWith(cookie+'='))?.split('=')[1];
        if(value==='ready')finish();
      },400);
      timeout=setTimeout(()=>finish('准备超时，已暂停后续下载。请先检查浏览器下载列表再重试。',true),300000);
      document.body.appendChild(frame);
    });
  }
  download.addEventListener('click',async()=>{
    if(busy||!selected().length)return;
    const queue=selected();let started=0;const failures=[];
    busy=true;error.classList.add('hidden');download.setAttribute('aria-busy','true');available.forEach(box=>box.disabled=true);sync();
    try{
      for(let i=0;i<queue.length;i++){
        download.textContent=`准备中 ${i+1}/${queue.length}`;
        status.textContent=`正在准备第 ${i+1}/${queue.length} 个 ZIP（批次 #${queue[i].value}），已发起 ${started} 个下载…`;
        const result=await startDownload(queue[i].value);
        if(result.message){failures.push(`批次 #${queue[i].value}：${result.message}`);if(result.stop)break;}
        else{started++;queue[i].checked=false;sync();}
      }
      status.textContent=`已发起 ${started}/${queue.length} 个 ZIP 下载，请在浏览器下载列表查看进度。`;
      if(failures.length)showError(failures.join('；')+' 未成功发起的批次已保留勾选。');
    }catch(_){showError('下载中断，请检查浏览器下载列表后重试剩余勾选的批次。');}
    finally{busy=false;available.forEach(box=>box.disabled=false);download.textContent='逐个下载选中批次';download.removeAttribute('aria-busy');sync();}
  });
  sync();
})();
