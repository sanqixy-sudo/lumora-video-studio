/* Keep an unfinished creation on this device, scoped to the signed-in account. */
(() => {
  function init() {
    const form = document.querySelector('#create-job-form[data-history-scope]');
    if (!form) return;
    const key = `lumora.creation-draft.v1.${form.dataset.historyScope}`;
    const notice = document.getElementById('creation-draft-notice');
    const message = document.getElementById('creation-draft-message');
    const recreateNotice = document.getElementById('creation-recreate-notice');
    const model = form.querySelector('#job-model-select');
    let timer = null;
    let restoring = false;
    let submitted = false;
    let dirty = false;
    let saved = null;
    let seed = null;
    let pendingSeedCompletion = null;
    try { saved = JSON.parse(localStorage.getItem(key) || 'null'); } catch (_) { /* Storage may be unavailable. */ }
    try { seed = JSON.parse(form.dataset.recreateSeed || 'null'); } catch (_) { /* Use an empty form. */ }
    if (!saved || !Array.isArray(saved.prompts) || !Number.isFinite(saved.updated_at) || Date.now() - saved.updated_at > 30 * 86400000) saved = null;

    const field = name => form.elements.namedItem(name);
    const signal = element => element?.dispatchEvent(new Event('change', { bubbles: true }));
    const promptValues = () => [...form.querySelectorAll('textarea[name="prompts"]')].map(el => el.value);
    function snapshot() {
      return {
        updated_at: Date.now(), model_choice: model?.value || '',
        product_name: field('product_name')?.value || '', region_name: field('region_name')?.value || '',
        batch_name: field('batch_name')?.value || '', resolution: field('resolution')?.value || '',
        aspect_ratio: field('aspect_ratio')?.value || '', seconds: field('seconds')?.value || '',
        reference_preset_id: field('reference_preset_id')?.value || '',
        image_urls: [...form.querySelectorAll('[name="omni_reference_image_urls"]')].map(el => el.value).filter(Boolean),
        standard_image_url: field('reference_image_url')?.value || '',
        omni_preset_ids: [...form.querySelectorAll('[name="omni_reference_preset_ids"]:checked')].map(el => el.value),
        video_url: field('omni_reference_video_url')?.value || '', prompts: promptValues(),
      };
    }
    function persist() {
      clearTimeout(timer);
      timer = null;
      if (restoring || submitted) return;
      const value = snapshot();
      const meaningful = value.model_choice || value.resolution || value.product_name.trim() || value.region_name.trim() || value.batch_name.trim() ||
        value.prompts.some(prompt => prompt.trim()) || value.standard_image_url.trim() ||
        value.reference_preset_id || value.image_urls.length || value.omni_preset_ids.length || value.video_url.trim();
      try {
        if (meaningful) localStorage.setItem(key, JSON.stringify(value));
        else localStorage.removeItem(key);
      } catch (_) { /* Creation still works without local storage. */ }
    }
    function scheduleSave() {
      if (restoring || submitted) return;
      dirty = true;
      notice.hidden = true;
      clearTimeout(timer);
      timer = setTimeout(persist, 500);
    }
    function restore(value) {
      restoring = true;
      try {
        if (model) {
          const choice = String(value.model_choice || '');
          model.value = [...model.options].some(option => option.value === choice) ? choice : '';
          signal(model);
        }
        for (const name of ['product_name', 'region_name', 'batch_name']) {
          if (field(name)) field(name).value = value[name] || '';
        }
        for (const name of ['resolution', 'aspect_ratio', 'seconds']) {
          const select = field(name);
          if (select && [...select.options].some(option => option.value === String(value[name]))) {
            select.value = String(value[name]);
            signal(select);
          }
        }
        const standard = field('reference_preset_id');
        const standardUrl = field('reference_image_url');
        const omniChecks = [...form.querySelectorAll('[name="omni_reference_preset_ids"]')];
        const rawUrls = Array.isArray(value.image_urls) ? value.image_urls.filter(url => typeof url === 'string') : [];
        const selectedIds = new Set(Array.isArray(value.omni_preset_ids) ? value.omni_preset_ids.map(String) : []);
        const isOmni = ['veo_omni', 'wuyin_omni', 'flow_omni', 'oaire_omni', 'oaire_grok'].includes(model?.selectedOptions[0]?.dataset.provider);
        if (isOmni) {
          const remainingUrls = [];
          for (const url of rawUrls) {
            const matching = omniChecks.find(el => el.dataset.url === url && !selectedIds.has(el.value));
            if (matching) selectedIds.add(matching.value);
            else remainingUrls.push(url);
          }
          omniChecks.forEach(el => { el.checked = selectedIds.has(el.value); signal(el); });
          const inputs = () => [...form.querySelectorAll('[name="omni_reference_image_urls"]')];
          inputs().slice(1).forEach(el => el.closest('.omni-image-url-row')?.remove());
          if (inputs()[0]) inputs()[0].value = '';
          remainingUrls.forEach((url, index) => {
            if (index > 0) form.dispatchEvent(new Event('lumora:add-omni-image-row'));
            const input = inputs()[index];
            if (input) { input.value = url; input.dispatchEvent(new Event('input', { bubbles: true })); }
          });
          const video = field('omni_reference_video_url');
          if (video) { video.value = value.video_url || ''; signal(video); }
        } else {
          const presetId = String(value.reference_preset_id || '');
          if (standard) { standard.value = [...standard.options].some(option => option.value === presetId) ? presetId : ''; signal(standard); }
          const imageUrl = value.standard_image_url || rawUrls[0] || '';
          if (standardUrl && (!standard?.value || standard.selectedOptions[0]?.dataset.url !== imageUrl)) {
            standardUrl.value = imageUrl;
            standardUrl.dispatchEvent(new Event('input', { bubbles: true }));
          }
        }
        form.dispatchEvent(new CustomEvent('lumora:restore-prompts', { detail: { prompts: value.prompts } }));
      } finally { restoring = false; }
    }
    function withCurrentText(value, modelChoice) {
      const current = snapshot();
      return { ...value, model_choice: modelChoice,
        product_name: current.product_name, region_name: current.region_name,
        batch_name: current.batch_name, prompts: current.prompts };
    }

    if (seed) {
      restore(seed);
      recreateNotice.hidden = false;
      recreateNotice.textContent = seed.model_unavailable
        ? `已载入任务 #${seed.source_job_id} 的内容。原模型现已不可用，请重新选择模型并核对素材。`
        : `已载入任务 #${seed.source_job_id} 的设置、素材和提示词；修改后可创建新任务。`;
      if (seed.local_reference_unavailable) recreateNotice.textContent += ' 原任务的本地上传图片无法自动带入，请重新添加素材。';
      if (seed.model_unavailable) {
        const completeUnavailableSeed = () => {
          if (!model.value) return;
          model.removeEventListener('change', completeUnavailableSeed);
          pendingSeedCompletion = null;
          restore(withCurrentText(seed, model.value));
          recreateNotice.textContent = `已按新模型载入任务 #${seed.source_job_id} 的内容，请核对规格和素材。${seed.local_reference_unavailable ? ' 原任务的本地上传图片无法自动带入，请重新添加素材。' : ''}`;
        };
        pendingSeedCompletion = completeUnavailableSeed;
        model.addEventListener('change', completeUnavailableSeed);
      }
    }
    if (saved) {
      notice.hidden = false;
      const time = new Date(saved.updated_at).toLocaleString('zh-CN');
      message.textContent = `发现 ${time} 保存的未提交草稿。`;
    }
    document.getElementById('creation-draft-restore')?.addEventListener('click', () => {
      if (!saved) return;
      if (pendingSeedCompletion) model.removeEventListener('change', pendingSeedCompletion);
      pendingSeedCompletion = null;
      restore(saved);
      notice.hidden = true;
      const missingModel = saved.model_choice && ![...model.options].some(option => option.value === saved.model_choice);
      recreateNotice.hidden = !missingModel;
      if (missingModel) {
        recreateNotice.textContent = '草稿原模型已不可用，请选择新模型并核对规格和素材。';
        const finishDraft = () => {
          if (!model.value) return;
          model.removeEventListener('change', finishDraft);
          restore(withCurrentText(saved, model.value));
          recreateNotice.textContent = '已按新模型载入草稿，请核对规格和素材。';
        };
        model.addEventListener('change', finishDraft);
      }
      dirty = true;
      persist();
    });
    document.getElementById('creation-draft-dismiss')?.addEventListener('click', () => {
      saved = null;
      notice.hidden = true;
      try { localStorage.removeItem(key); } catch (_) {}
    });
    form.addEventListener('input', scheduleSave);
    form.addEventListener('change', scheduleSave);
    form.addEventListener('click', event => {
      if (event.target.closest('#add-prompt-btn,[data-remove-prompt],[data-copy-prompt],#omni-add-image,.omni-remove-image,#batch-import-apply,#batch-prefix-apply')) {
        setTimeout(scheduleSave, 0);
      }
    });
    window.addEventListener('pagehide', () => { if (dirty) persist(); });
    document.addEventListener('lumora:saved', event => {
      if (event.detail?.form !== form) return;
      submitted = true;
      clearTimeout(timer);
      try { localStorage.removeItem(key); } catch (_) {}
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();
})();
