(() => {
  const base = window.BATCH_DATA_ENDPOINT;
  if (!base) return;
  const bulk = document.getElementById('batch-regenerate');
  const error = document.getElementById('batch-recovery-error');
  let busy = false;
  const buttons = () => [...document.querySelectorAll('#batch-regenerate,[data-regenerate],[data-retry-download]')];
  function sync(payload) {
    const count = payload.jobs.filter(job => job.can_regenerate).length;
    bulk.classList.toggle('hidden', !count);
    if (!busy) bulk.textContent = `重新生成失败项 · ${count}`;
    payload.jobs.forEach(job => {
      const row = document.querySelector(`[data-batch-job="${Number(job.id)}"]`);
      if (!row) return;
      row.querySelector('[data-regenerate]')?.classList.toggle('hidden', !job.can_regenerate);
      row.querySelector('[data-retry-download]')?.classList.toggle('hidden', !job.can_retry_download);
      row.querySelector('[data-job-recovery-reason]').textContent = job.regeneration_reason || '';
      row.querySelector('[data-job-failure]').textContent = ['failed','download_failed'].includes(job.status) ? (job.error_message || job.error_text || '') : '';
    });
  }
  document.addEventListener('lumora:batch-updated', event => sync(event.detail));
  async function request(url, data) {
    const response = await fetch(url, {credentials:'same-origin',headers:{'Accept':'application/json',...(data ? {'Content-Type':'application/json'} : {})},...(data ? {method:'POST',body:JSON.stringify(data)} : {})});
    if (response.status === 401) { location.assign(`/login?next=${encodeURIComponent(location.pathname)}&expired=1`); throw new Error('登录已过期，请重新登录。'); }
    const type = response.headers.get('content-type') || '';
    const body = type.includes('json') ? await response.json() : null;
    if (!response.ok || !body) throw new Error(typeof body?.detail === 'string' ? body.detail : `操作未完成（HTTP ${response.status}），请刷新后重试。`);
    return body;
  }
  async function run(button, mode, id) {
    if (busy) return;
    busy = true;
    error.classList.add('hidden');
    const label = button.textContent;
    buttons().forEach(item => item.disabled = true);
    button.setAttribute('aria-busy','true');
    button.textContent = mode === 'download' ? '正在加入下载队列…' : '正在检查…';
    let submitted = false;
    try {
      if (mode === 'download') {
        await request(`${base}/jobs/${id}/retry-download`, {});
      } else {
        const quote = await request(`${base}/regeneration-preview${id ? '?job_id='+id : ''}`);
        button.textContent = label;
        const skipped = quote.skipped.length ? ` 另有 ${quote.skipped.length} 条暂不能重做。` : '';
        const confirmed = await SoraUI.confirm(`将在原批次重做 ${quote.count} 条失败项，预占 ${quote.quota} 次额度，上游接受后按现有规则扣除。成功作品和正在处理的任务不受影响。${skipped}`, {title:'重新生成失败项',label:'确认重新生成'});
        if (!confirmed) return;
        button.textContent = '正在加入生成队列…';
        await request(`${base}/regenerate`, {job_ids:quote.job_ids});
      }
      submitted = true;
      button.textContent = '已加入队列';
      location.reload();
    } catch (cause) {
      error.textContent = cause.message;
      error.classList.remove('hidden');
    } finally {
      if (!submitted) { busy = false; buttons().forEach(item => item.disabled = false); button.textContent = label; button.removeAttribute('aria-busy'); button.focus({preventScroll:true}); }
    }
  }
  bulk.addEventListener('click', () => run(bulk, 'generate'));
  document.querySelectorAll('[data-regenerate]').forEach(button => button.addEventListener('click', () => run(button,'generate',Number(button.dataset.regenerate))));
  document.querySelectorAll('[data-retry-download]').forEach(button => button.addEventListener('click', () => run(button,'download',Number(button.dataset.retryDownload))));
})();
