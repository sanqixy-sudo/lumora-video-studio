(() => {
  document.querySelectorAll('[data-reference-image]').forEach(image => {
    const preview = image.closest('[data-reference-preview]');
    const status = preview.querySelector('[data-reference-status]');
    function showResult() {
      const ready = image.complete && image.naturalWidth > 0;
      preview.classList.toggle('is-ready', ready);
      preview.classList.toggle('is-error', !ready);
      status.textContent = ready ? '' : '图片暂时无法显示，可打开原链接查看';
    }
    image.addEventListener('load', showResult);
    image.addEventListener('error', showResult);
    if (image.complete) showResult();
  });
})();
