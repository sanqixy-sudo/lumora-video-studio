(() => {
  const dialog = document.querySelector('[data-usage-dialog]');
  const content = dialog?.querySelector('[data-usage-detail-content]');
  const title = dialog?.querySelector('#usage-detail-title');
  if (!dialog || !content) return;
  let opener = null;
  let requestNumber = 0;
  const skeleton = '<div class="usage-detail-grid usage-detail-skeleton" aria-hidden="true"><div class="usage-detail-facts"><div class="usage-skeleton-line wide"></div><div class="usage-skeleton-line"></div><div class="usage-skeleton-line"></div><div class="usage-skeleton-line wide"></div><div class="usage-skeleton-block"></div></div><div class="usage-skeleton-video"></div></div><span class="wb-sr-only">正在读取任务详情…</span>';

  async function openDetail(button) {
    opener = button;
    title.textContent = `任务 #${button.dataset.usageDetail}`;
    const thisRequest = ++requestNumber;
    content.className = 'usage-detail-content is-loading';
    content.innerHTML = skeleton;
    dialog.showModal();
    try {
      const response = await fetch(`/usage-logs/${encodeURIComponent(button.dataset.usageDetail)}/detail`, {
        credentials: 'same-origin', redirect: 'error', headers: { Accept: 'text/html' },
      });
      if (!response.ok || !response.headers.get('content-type')?.includes('text/html')) throw new Error('detail unavailable');
      const html = await response.text();
      if (thisRequest !== requestNumber || !dialog.open) return;
      content.className = 'usage-detail-content';
      content.innerHTML = html;
    } catch (_) {
      if (thisRequest !== requestNumber || !dialog.open) return;
      content.className = 'usage-detail-content';
      content.textContent = '暂时无法读取任务详情，请关闭弹窗后重试。';
    }
  }

  document.addEventListener('click', event => {
    const button = event.target.closest('[data-usage-detail]');
    if (button) openDetail(button);
  });
  content.addEventListener('click', async event => {
    const button = event.target.closest('[data-recheck-job]');
    if (!button || button.disabled) return;
    const status = content.querySelector('[data-recheck-status]');
    button.disabled = true;
    if (status) status.textContent = '正在安排核对…';
    try {
      const response = await fetch(`/usage-logs/${encodeURIComponent(button.dataset.recheckJob)}/recheck`, {
        method: 'POST', credentials: 'same-origin', redirect: 'error', headers: { Accept: 'application/json' },
      });
      if (!response.ok) throw new Error('recheck failed');
      if (status) status.textContent = '已加入核对队列，请稍后刷新日志查看结果。';
    } catch (_) {
      button.disabled = false;
      if (status) status.textContent = '暂时无法安排核对，请稍后重试。';
    }
  });
  dialog.querySelector('[data-close-usage-detail]').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => {
    requestNumber++;
    content.querySelectorAll('video').forEach(video => video.pause());
    content.replaceChildren();
    opener?.focus();
  });
  dialog.addEventListener('click', event => {
    if (event.target === dialog) dialog.close();
  });
})();
