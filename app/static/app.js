function fileDownloadUrl(job) {
  return job.output_file ? `/app/files/${job.output_file.id}/download` : "#";
}

function fileStreamUrl(job) {
  return job.output_file ? `/app/files/${job.output_file.id}/stream` : "#";
}

let followLogs = true;
let toastTimer = null;

function showToast(message, type = "info") { SoraUI.toast(message, type); }

async function copyTextToClipboard(text) {
  const value = String(text || "");
  if (navigator.clipboard?.writeText && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(value);
      return true;
    } catch (_) {
      // Fall through to the textarea strategy for HTTP or embedded browsers.
    }
  }
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  textarea.style.top = "0";
  const previousFocus=document.activeElement;
  (document.querySelector('dialog[open],.modal:not(.hidden),.plaza-modal:not(.hidden)')||document.body).appendChild(textarea);
  textarea.focus();
  textarea.select();
  textarea.setSelectionRange(0, textarea.value.length);
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch (_) {
    ok = false;
  }
  textarea.remove();
  previousFocus?.focus({preventScroll:true});
  return ok;
}

function initCopyTextButtons() {
  document.addEventListener("click", async (event) => {
    const btn = event.target.closest("[data-copy-text]");
    if (!btn) return;
    const sourceSelector = btn.dataset.copySource || "";
    const source = sourceSelector ? btn.closest("[data-copy-scope]")?.querySelector(sourceSelector) || document.querySelector(sourceSelector) : null;
    const text = source ? source.textContent || "" : btn.dataset.copyText || "";
    const label = btn.dataset.copyLabel || "内容";
    if (!text.trim()) {
      showToast(`暂无可复制${label}`, "error");
      return;
    }
    const copied = await copyTextToClipboard(text);
    if (copied) {
      SoraUI.feedback(btn,"已复制");
    } else {
      showToast("复制失败，请手动复制。", "error");
    }
  });
}

function initToasts() {
  const flashMessage = sessionStorage.getItem("app.toast.message");
  const flashType = sessionStorage.getItem("app.toast.type") || "info";
  if (flashMessage) {
    sessionStorage.removeItem("app.toast.message");
    sessionStorage.removeItem("app.toast.type");
    showToast(flashMessage, flashType);
  } else if (window.PAGE_TOAST) {
    showToast(window.PAGE_TOAST, window.PAGE_TOAST_TYPE || "info");
  }
}

function initLoginModeSwitch() {
  const loginForm = document.querySelector("[data-login-form]");
  const registerForm = document.querySelector("[data-register-form]");
  const switchRow = document.querySelector("[data-login-switch-row]");
  if (!loginForm || !registerForm) return;
  const title = document.getElementById("login-panel-title");
  const subtitle = document.getElementById("login-panel-subtitle");
  const setMode = (mode) => {
    const isRegister = mode === "register";
    loginForm.classList.toggle("hidden", isRegister);
    registerForm.classList.toggle("hidden", !isRegister);
    switchRow?.classList.toggle("hidden", isRegister);
    if (title) title.textContent = isRegister ? "注册新账号" : "登录控制台";
    if (subtitle) subtitle.textContent = isRegister ? "填写信息后进入创作工作台" : "继续你的创作工作台";
  };
  document.querySelector("[data-show-register]")?.addEventListener("click", () => setMode("register"));
  document.querySelector("[data-show-login]")?.addEventListener("click", () => setMode("login"));
}

function currentLoginUrl() {
  const next = encodeURIComponent(window.location.pathname + window.location.search);
  return `/login?next=${next}&expired=1`;
}

async function fetchJSON(url, options = {}) {
  const response = await fetch(url, { credentials: "same-origin", ...options });
  const isLoginRequest = new URL(url, location.href).pathname === "/auth/login-browser";
  if (!isLoginRequest && (response.status === 401 || (response.redirected && new URL(response.url).pathname === "/login"))) {
    window.location.assign(currentLoginUrl());
    throw new Error("登录已过期，正在跳转登录页。");
  }
  const text = await response.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch (_) {
    data = null;
  }
  if (!response.ok) {
    const fallback = response.status === 403
      ? (isLoginRequest ? "登录请求被拒绝（HTTP 403），请联系管理员检查账号状态或访问限制。" : "没有执行此操作的权限。")
      : `请求失败（HTTP ${response.status}）`;
    const detail = data?.detail === "Forbidden" ? fallback : (data?.detail || fallback);
    const error = new Error(SoraUI.message(detail)); error.detail = detail; throw error;
  }
  return data;
}

function formDataToObject(form) {
  const formData = new FormData(form);
  const payload = {};
  for (const [key, value] of formData.entries()) {
    payload[key] = typeof value === "string" && form.elements.namedItem(key)?.type !== "password" ? value.trim() : value;
  }
  return payload;
}

function renderEvents(events) {
  return events.map((event) => `[${event.created_at}] ${event.message}`).join("\n");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('\"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderApiCalls(calls) {
  if (!Array.isArray(calls) || calls.length === 0) {
    return '<div class="empty-state compact-empty">暂无提交记录。任务还没有开始提交上游，或旧版本没有记录。</div>';
  }
  return calls.map((call) => {
    const okClass = call.success ? "success" : "failed";
    const okText = call.success ? "是" : "否";
    const status = call.status_code ?? "-";
    const latency = call.latency_ms ?? "-";
    const request = call.request_summary ? `<pre>请求：${escapeHtml(call.request_summary)}</pre>` : "";
    const response = call.response_summary ? `<pre>响应：${escapeHtml(call.response_summary)}</pre>` : "";
    const error = call.error_text ? `<pre>错误：${escapeHtml(call.error_text)}</pre>` : "";
    return `
      <div class="api-call-card ${okClass}">
        <div class="api-call-head"><strong>#${escapeHtml(call.id)} ${escapeHtml(call.method)} ${escapeHtml(call.endpoint)}</strong><span>${escapeHtml(call.created_at)}</span></div>
        <div class="api-call-meta">状态码：${escapeHtml(status)} / 成功：${okText} / 耗时：${escapeHtml(latency)}ms</div>
        ${request}${response}${error}
      </div>`;
  }).join("");
}

function statusClass(status) {
  return `status-${status || "unknown"}`;
}

function shouldShowIndeterminateProgress(job) {
  const active = ["queued", "submitting", "submitted", "polling", "remote_completed", "download_waiting", "downloading"];
  return active.includes(job.status) && Number(job.progress || 0) <= 0;
}

function updateProgressDisplay(job) {
  const progressText = document.getElementById("job-progress-text");
  const progressBar = document.getElementById("job-progress-bar");
  if (!progressText || !progressBar) return;
  if (shouldShowIndeterminateProgress(job)) {
    const labelMap = {
      queued: "排队中",
      submitting: "提交中",
      submitted: "已提交",
      polling: "生成中",
      remote_completed: "准备下载",
      download_waiting: "等待下载",
      downloading: "下载中",
    };
    progressText.textContent = labelMap[job.status] || "处理中…";
    progressBar.classList.add("indeterminate");
    if (document.body.classList.contains("wb")) progressBar.style.transform = "scaleX(.38)"; else progressBar.style.width = "38%";
  } else {
    progressText.textContent = `${job.progress}%`;
    progressBar.classList.remove("indeterminate");
    if (document.body.classList.contains("wb")) progressBar.style.transform = `scaleX(${Math.max(0,Math.min(100,Number(job.progress)||0))/100})`; else progressBar.style.width = `${job.progress}%`;
  }
}

function updateJobView(payload) {
  const job = payload.job;
  document.getElementById("job-status").className = `badge big-badge ${statusClass(job.status)}`;
  document.getElementById("job-status").textContent = job.status_label || job.status;
  updateProgressDisplay(job);
  document.getElementById("job-remote").textContent = job.remote_task_id || "-";
  const queueEl = document.getElementById("job-queue");
  if (queueEl) queueEl.textContent = job.queue_text || "-";
  const displayedError = job.error_message || job.error_text || "";
  const errorEl = document.getElementById("job-error");
  if (errorEl) errorEl.textContent = displayedError || "-";
  document.getElementById("job-error-panel")?.classList.toggle("hidden", !displayedError);
  const errorCodeEl = document.getElementById("job-error-code");
  if (errorCodeEl) errorCodeEl.textContent = job.error_code ? `错误码：${job.error_code}` : "";
  const upstreamResponseEl = document.querySelector("#job-upstream-response pre");
  if (upstreamResponseEl && job.upstream_response) upstreamResponseEl.textContent = JSON.stringify(job.upstream_response, null, 2);
  const attemptEl = document.getElementById("job-download-attempts");
  if (attemptEl) attemptEl.textContent = job.download_attempts ?? 0;

  const logs = document.getElementById("job-logs");
  if (logs) {
    logs.textContent = renderEvents(payload.events);
    if (followLogs) logs.scrollTop = logs.scrollHeight;
  }
  const apiCallList = document.getElementById("api-call-list");
  if (apiCallList) {
    apiCallList.innerHTML = renderApiCalls(payload.api_calls);
  }

  const downloadBtn = document.getElementById("download-btn");
  const remoteDownloadBtn = document.getElementById("remote-download-btn");
  const copyRemoteLinkBtn = document.getElementById("copy-remote-link-btn");
  const player = document.getElementById("job-player");
  const playerWrap = document.getElementById("player-wrap");
  const playerEmpty = document.getElementById("player-empty");
  const hasFile = Boolean(job.output_file);

  if (downloadBtn) downloadBtn.classList.toggle("hidden", !hasFile);
  if (remoteDownloadBtn) {
    remoteDownloadBtn.classList.toggle("hidden", !job.remote_download_url);
    if (job.remote_download_url) remoteDownloadBtn.href = job.remote_download_url;
  }
  if (copyRemoteLinkBtn) {
    copyRemoteLinkBtn.classList.toggle("hidden", !job.public_remote_download_url);
    if (job.public_remote_download_url) copyRemoteLinkBtn.dataset.url = job.public_remote_download_url;
  }
  if (hasFile) {
    if (downloadBtn) downloadBtn.href = fileDownloadUrl(job);
    if (player && player.getAttribute("src") !== fileStreamUrl(job)) player.src = fileStreamUrl(job);
    player?.classList.remove("hidden");
    playerWrap?.classList.remove("hidden");
    playerEmpty?.classList.add("hidden");
  } else {
    player?.classList.add("hidden");
    playerWrap?.classList.add("hidden");
    playerEmpty?.classList.remove("hidden");
  }

  document.getElementById("redownload-btn")?.classList.toggle("hidden", !payload.can_redownload);
  document.getElementById("resume-btn")?.classList.toggle("hidden", !payload.can_resume);
  document.getElementById("pause-btn")?.classList.toggle("hidden", !payload.can_pause);
  return job;
}

function initAsyncForms() {
  document.querySelectorAll("form[data-async-json]").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (form.dataset.busy === "true") return;
      form.dataset.busy = "true";
      if (form.hasAttribute("data-login-form")) document.querySelector(".wb-login-notice")?.classList.add("hidden");
      const endpoint = form.dataset.asyncJson;
      const redirect = form.dataset.successRedirect;
      const submitButton = form.querySelector('button[type="submit"]');
      const originalText = submitButton?.innerHTML || "";
      const loadingText = submitButton?.dataset.loadingText || "处理中…";

      if (submitButton) {
        submitButton.disabled = true;
        submitButton.textContent = loadingText;
        submitButton.setAttribute("aria-busy", "true");
        submitButton.classList.add("is-loading");
      }

      try {
        const payload = formDataToObject(form);
        const result = await fetchJSON(endpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const target = result?.target || redirect;
        const successMessage = form.dataset.successMessage;
        if (target) {
          if (successMessage) {
            sessionStorage.setItem("app.toast.message", successMessage);
            sessionStorage.setItem("app.toast.type", "info");
          }
          document.dispatchEvent(new CustomEvent('lumora:saved',{detail:{form}}));window.location.assign(target);
          return;
        }
        if (successMessage) {
          showToast(successMessage, "info");
        }
        document.dispatchEvent(new CustomEvent('lumora:saved',{detail:{form}}));window.location.reload();
      } catch (error) {
        SoraUI.formError(form, error);
      } finally {
        delete form.dataset.busy;
        if (submitButton) {
          submitButton.disabled = false;
          submitButton.innerHTML = originalText;
          submitButton.removeAttribute("aria-busy");
          submitButton.classList.remove("is-loading");
        }
      }
    });
  });
}

function initJobDetailPage() {
  if (!window.JOB_DATA_ENDPOINT) return;
  const copyBtn = document.getElementById("copy-logs-btn");
  const toggleFollowBtn = document.getElementById("toggle-follow-btn");
  const toggleRefreshBtn = document.getElementById("toggle-refresh-btn");
  const refreshState = document.getElementById("auto-refresh-state");
  const redownloadBtn = document.getElementById("redownload-btn");
  const resumeBtn = document.getElementById("resume-btn");
  const pauseBtn = document.getElementById("pause-btn");
  const logs = document.getElementById("job-logs");
  const copyRemoteLinkBtn = document.getElementById("copy-remote-link-btn");

  let autoRefresh = true;
  let timer = null;
  let lastJobStatus = null;
  let refreshFailures = 0;

  function refreshDelay() {
    return Math.min(5000 * 2 ** refreshFailures, 60000);
  }

  function updateRefreshState(text) {
    if (refreshState) refreshState.textContent = text;
    if (toggleRefreshBtn) toggleRefreshBtn.textContent = autoRefresh ? "暂停刷新" : "恢复刷新";
  }

  function stopAuto(text = "刷新已暂停") {
    if (timer) clearTimeout(timer);
    timer = null;
    updateRefreshState(text);
  }

  function scheduleAuto() {
    if (!autoRefresh || timer || document.hidden) return;
    updateRefreshState(refreshFailures ? "更新暂时失败，正在重试" : "自动刷新中");
    timer = setTimeout(async () => {
      timer = null;
      await refresh();
      if (autoRefresh) scheduleAuto();
    }, refreshDelay());
  }

  async function refresh() {
    try {
      const payload = await fetchJSON(window.JOB_DATA_ENDPOINT);
      if (!payload) return;
      refreshFailures = 0;
      const job = updateJobView(payload);
      lastJobStatus = job.status;
      if (["completed", "cancelled", "interrupted", "failed", "download_failed"].includes(job.status)) {
        autoRefresh = false;
        stopAuto("已停止刷新");
      }
    } catch (error) {
      console.error(error);
      refreshFailures++;
      updateRefreshState("更新暂时失败，稍后自动重试");
    }
  }

  copyBtn?.addEventListener("click", async () => {
    const text = logs?.textContent || "";
    try {
      const copied = await copyTextToClipboard(text);
      if (!copied) throw new Error("copy failed");
      showToast("日志已复制", "info");
      copyBtn.textContent = "已复制";
      setTimeout(() => {
        copyBtn.textContent = "复制日志";
      }, 1200);
    } catch {
      showToast("复制失败，请手动复制。", "error");
    }
  });

  copyRemoteLinkBtn?.addEventListener("click", async () => {
    const path = copyRemoteLinkBtn.dataset.url || "";
    if (!path) return showToast("暂无可复制的远端下载链接。", "error");
    const url = new URL(path, window.location.origin).toString();
    try {
      const copied = await copyTextToClipboard(url);
      if (!copied) throw new Error("copy failed");
      showToast("临时下载链接已复制", "info");
    } catch {
      showToast("复制失败，请手动复制。", "error");
    }
  });

  toggleFollowBtn?.addEventListener("click", () => {
    followLogs = !followLogs;
    toggleFollowBtn.textContent = followLogs ? "暂停跟随" : "恢复跟随";
  });

  toggleRefreshBtn?.addEventListener("click", async () => {
    autoRefresh = !autoRefresh;
    if (autoRefresh) {
      updateRefreshState("正在刷新");
      await refresh();
      scheduleAuto();
    } else {
      stopAuto("刷新已暂停");
    }
  });

  document.addEventListener("visibilitychange", () => {
    if (!autoRefresh || ["completed", "cancelled", "interrupted", "failed", "download_failed"].includes(lastJobStatus)) return;
    stopAuto(document.hidden ? "页面隐藏，暂停刷新" : "自动刷新中");
    scheduleAuto();
  });

  redownloadBtn?.addEventListener("click", async () => {
    if (redownloadBtn.disabled) return;
    redownloadBtn.disabled = true;
    try {
    if (!await SoraUI.confirm("确认重新下载这个任务的结果文件吗？这不会重新创建任务，也不会再次扣费。")) return;
    await fetchJSON(`${window.JOB_DATA_ENDPOINT}/redownload`, { method: "POST" });
    autoRefresh = true;
    await refresh();
    scheduleAuto();
    } catch (error) { showToast(error.message, "error"); }
    finally { redownloadBtn.disabled = false; }
  });

  resumeBtn?.addEventListener("click", async () => {
    if (resumeBtn.disabled) return;
    resumeBtn.disabled = true;
    try {
    if (!await SoraUI.confirm("确认继续重试这个任务吗？如果远端视频已经可下载，系统会直接尝试保存到本地。")) return;
    await fetchJSON(`${window.JOB_DATA_ENDPOINT}/resume`, { method: "POST" });
    autoRefresh = true;
    await refresh();
    scheduleAuto();
    } catch (error) { showToast(error.message, "error"); }
    finally { resumeBtn.disabled = false; }
  });

  pauseBtn?.addEventListener("click", async () => {
    if (pauseBtn.disabled) return;
    pauseBtn.disabled = true;
    try {
    if (!await SoraUI.confirm("确认暂停这个任务的自动重试吗？暂停后不会继续自动查询，直到你再次点击继续重试。")) return;
    await fetchJSON(`${window.JOB_DATA_ENDPOINT}/pause`, { method: "POST" });
    autoRefresh = false;
    stopAuto("已停止刷新");
    await refresh();
    } catch (error) { showToast(error.message, "error"); }
    finally { pauseBtn.disabled = false; }
  });

  refresh();
  scheduleAuto();
}
function initTabs() {
  function activateTab(button) {
    if (!button) return;
    const target = button.dataset.tabTarget;
    if (target) history.replaceState(null, "", `#${target}`);
    const card = button.closest(".task-tabs-card") || document;
    card.querySelectorAll(".tab-button").forEach((item) => item.classList.toggle("active", item === button));
    card.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.toggle("active", panel.dataset.tabPanel === target));
  }
  document.querySelectorAll(".tab-button[data-tab-target]").forEach((button) => {
    button.addEventListener("click", () => activateTab(button));
  });
  const hashTarget = (window.location.hash || "").replace("#", "");
  if (hashTarget) {
    document.querySelectorAll(".tab-button[data-tab-target]").forEach((button) => { if (button.dataset.tabTarget === hashTarget) activateTab(button); });
  }
}

function initRowMenus() {
  document.addEventListener("click", (event) => {
    const trigger = event.target.closest(".menu-trigger");
    document.querySelectorAll(".row-menu.open").forEach((menu) => {
      if (!trigger || menu !== trigger.closest(".row-menu")) menu.classList.remove("open");
    });
    if (trigger) {
      event.preventDefault();
      trigger.closest(".row-menu")?.classList.toggle("open");
    }
  });
}

function initToggleEditBlocks() {
  document.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-toggle-edit]");
    if (!btn) return;
    event.preventDefault();
    const id = btn.dataset.toggleEdit;
    if (!id) return;
    const target = document.getElementById(id);
    if (target) target.classList.toggle("hidden");
  });
}

function initUsernameConfirmForms() { /* Shared POST form handler in ui.js. */ }

function initCreateJobForm() {
  const form = document.getElementById("create-job-form");
  const sizeSelect = document.getElementById("job-size-select");
  const secondsSelect = document.getElementById("job-seconds-select");
  const modelSelect = document.getElementById("job-model-select");
  const presetSelect = document.getElementById("reference-preset-select");
  const urlInput = document.getElementById("reference-image-url");
  const standardReferenceField = document.getElementById("standard-reference-field");
  const omniMaterialCard = document.getElementById("omni-material-card");
  const omniMaterialTitle = document.getElementById("omni-material-title");
  const omniMaterialCount = document.getElementById("omni-material-count");
  const omniMaterialDescription = document.getElementById("omni-material-description");
  const omniMaterialHint = document.getElementById("omni-material-hint");
  const omniVideoBlock = document.getElementById("omni-video-block");
  const omniVideoLabel = document.getElementById("omni-video-label");
  const omniVideoHint = document.getElementById("omni-video-hint");
  const omniVideoInput = document.getElementById("omni-reference-video-url");
  const omniImageUrlList = document.getElementById("omni-image-url-list");
  const omniAddImage = document.getElementById("omni-add-image");
  let hint = document.getElementById("reference-image-hint");
  const imageName = document.getElementById("reference-image-name");
  const imageDimensions = document.getElementById("reference-image-dimensions");
  const previewImage = document.getElementById("reference-image-preview-img");
  const emptyText = document.getElementById("reference-empty-text");
  const ratioFrame = document.getElementById("reference-ratio-frame");
  const submitButton = form?.querySelector('button[type="submit"]');
  const promptList = document.getElementById("prompt-list");
  const addPromptBtn = document.getElementById("add-prompt-btn");
  const promptCountText = document.getElementById("prompt-count-text");
  const quotaCostText = document.getElementById("quota-cost-text");
  const importToggle = document.getElementById("batch-import-toggle");
  const importBox = document.getElementById("batch-import-box");
  const importTextarea = document.getElementById("batch-import-textarea");
  const importApply = document.getElementById("batch-import-apply");
  const importCancel = document.getElementById("batch-import-cancel");
  if (!form || !sizeSelect || !secondsSelect || !promptList) return;
  if (!hint) {
    hint = document.createElement("div");
    hint.id = "reference-image-hint";
    hint.className = "field-hint reference-image-hint";
    ratioFrame?.closest(".reference-ratio-card")?.after(hint);
  }

  let latestImageCheckToken = 0;
  let referenceUrlTimer = null;
  let lastReferenceUrlValue = "";
  let lastOmniProvider = "";

  const imageConfirmations = new Map();
  function syncImageConfirmations(reset = false) {
    const inputs = [urlInput, ...omniImageInputs()].filter(Boolean);
    for (const [input, checkbox] of imageConfirmations) {
      if (!input.isConnected) { checkbox.closest('label').remove(); imageConfirmations.delete(input); }
    }
    for (const input of inputs) {
      let checkbox = imageConfirmations.get(input);
      if (!checkbox) {
        const label = document.createElement('label');label.className = 'checkline wb-image-confirm';
        checkbox = document.createElement('input');checkbox.type = 'checkbox';checkbox.autocomplete = 'off';checkbox.name = 'confirmed_reference_image_urls';
        const text = document.createElement('span');text.textContent = '我确认图片可用，跳过读取检查';
        label.append(checkbox,text);
        const note = document.createElement('small');note.textContent = '跳过本机读取及尺寸检查，生成渠道仍需读取图片。';note.hidden = true;label.append(note);
        if (input === urlInput) input.closest('label').after(label);else input.closest('.omni-image-url-row').append(label);
        checkbox.addEventListener('change',()=>{note.hidden = !checkbox.checked;if(input===urlInput)void validateReferenceUrl();});
        imageConfirmations.set(input,checkbox);
      }
      const value = normalizeUrl(input.value);
      if (reset || checkbox.value !== value) checkbox.checked = false;
      checkbox.value = value;
      checkbox.disabled = input.disabled || !value;
      if (checkbox.disabled) checkbox.checked = false;
      checkbox.closest('label').querySelector('small').hidden = !checkbox.checked;
    }
  }


  function selectedProvider() {
    return modelSelect?.selectedOptions?.[0]?.dataset.provider || "";
  }

  function omniPresetChecks() {
    return Array.from(omniMaterialCard?.querySelectorAll('input[name="omni_reference_preset_ids"]') || []);
  }

  function omniImageInputs() {
    return Array.from(omniImageUrlList?.querySelectorAll('input[name="omni_reference_image_urls"]') || []);
  }

  function omniImageCount() {
    const presetCount = omniPresetChecks().filter((input) => input.checked).length;
    const urlCount = omniImageInputs().filter((input) => input.value.trim()).length;
    return presetCount + urlCount;
  }

  function omniMaxImages() {
    return Number.parseInt(omniMaterialCard?.dataset.maxImages || "0", 10) || 0;
  }

  function resetOmniMaterials() {
    omniPresetChecks().forEach((input) => { input.checked = false; });
    const rows = Array.from(omniImageUrlList?.querySelectorAll(".omni-image-url-row") || []);
    rows.forEach((row, index) => {
      if (index === 0) row.querySelector("input").value = "";
      else row.remove();
    });
    if (omniVideoInput) omniVideoInput.value = "";
  }

  function refreshOmniCount() {
    const count = omniImageCount();
    const maximum = omniMaxImages();
    if (omniMaterialCount) omniMaterialCount.textContent = `${count} / ${maximum} 张`;
    omniMaterialCard?.classList.toggle("is-limit", count >= maximum && maximum > 0);
    omniPresetChecks().forEach((input) => {
      input.disabled = omniMaterialCard?.classList.contains("hidden") || (!input.checked && count >= maximum);
    });
    omniImageInputs().forEach((input) => {
      input.disabled = omniMaterialCard?.classList.contains("hidden") || (!input.value.trim() && count >= maximum);
    });
    const rows = Array.from(omniImageUrlList?.querySelectorAll(".omni-image-url-row") || []);
    rows.forEach((row) => {
      const remove = row.querySelector(".omni-remove-image");
      if (remove) remove.disabled = omniMaterialCard?.classList.contains("hidden");
    });
    if (omniAddImage) omniAddImage.disabled = omniMaterialCard?.classList.contains("hidden") || rows.length >= maximum || count >= maximum;
    syncImageConfirmations();
  }

  function syncOmniMode() {
    const isWuyin = selectedProvider() === "wuyin_omni";
    omniVideoBlock?.classList.toggle("hidden", !isWuyin);
    if (omniVideoInput) { omniVideoInput.disabled = !isWuyin; omniVideoInput.required = false; if (!isWuyin) omniVideoInput.value = ""; }
  }

  function syncModelSeconds() {
    if (!modelSelect) return;
    const option = modelSelect.selectedOptions?.[0];
    secondsSelect.value = option?.dataset.seconds || "";
    syncImageConfirmations(true);
    const provider = selectedProvider();
    const isOmni = ["veo_omni", "wuyin_omni"].includes(provider);
    if (isOmni && lastOmniProvider && lastOmniProvider !== provider) resetOmniMaterials();
    if (isOmni) lastOmniProvider = provider;
    standardReferenceField?.classList.toggle("hidden", isOmni);
    standardReferenceField?.querySelectorAll("input,select").forEach((control) => { control.disabled = isOmni; });
    omniMaterialCard?.classList.toggle("hidden", !isOmni);
    omniMaterialCard?.querySelectorAll("input,button").forEach((control) => { control.disabled = !isOmni; });
    if (isOmni) {
      const isVeo = provider === "veo_omni";
      const maximum = isVeo ? 6 : 1;
      omniMaterialCard.dataset.maxImages = String(maximum);
      if (omniMaterialTitle) omniMaterialTitle.textContent = isVeo ? "VEO Omni 输入素材" : "Wuyin Omni 输入素材";
      if (omniMaterialDescription) omniMaterialDescription.textContent = isVeo
        ? "选择 1–6 张参考图，生成一个视频。"
        : "可使用 1 张参考图和 1 个参考视频，均填写公网 URL。";
      if (omniMaterialHint) omniMaterialHint.textContent = `预设按列表顺序、图片链接按填写顺序提交，合计最多 ${maximum} 张。`;
    }
    syncOmniMode();
    refreshOmniCount();
  }

  function addOmniImageRow() {
    const maximum = omniMaxImages();
    const rows = omniImageUrlList?.querySelectorAll(".omni-image-url-row").length || 0;
    if (!omniImageUrlList || rows >= maximum) return;
    const row = document.createElement("div");
    row.className = "omni-image-url-row";
    const input = document.createElement("input");
    input.name = "omni_reference_image_urls";
    input.type = "url";input.autocomplete="off";input.spellcheck=false;
    input.setAttribute("aria-label", "参考图片链接");
    input.placeholder = "https://example.com/reference-image.jpg…";
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "omni-remove-image";
    remove.setAttribute("aria-label", "移除图片链接");
    remove.textContent = "移除";
    row.append(input, remove);
    omniImageUrlList.append(row);
    input.focus();
    refreshOmniCount();
  }

  function validateOmniMaterials() {
    const provider = selectedProvider();
    if (!["veo_omni", "wuyin_omni"].includes(provider)) return true;
    const count = omniImageCount();
    const maximum = omniMaxImages();
    if (count > maximum) {
      showToast(`当前渠道最多支持 ${maximum} 张参考图。`, "error");
      return false;
    }
    if (provider === "veo_omni" && count < 1) {
      showToast("VEO Omni 至少需要 1 张参考图。", "error");
      omniMaterialCard?.scrollIntoView({block:"center",behavior:matchMedia("(prefers-reduced-motion: reduce)").matches?"auto":"smooth"});
      return false;
    }
    return true;
  }

  function updateHint(message, isError = false) {
    hint.textContent = message;
    hint.style.color = isError ? "var(--wb-error)" : "";
  }

  function expectedSizeText() {
    return sizeSelect.value || "";
  }

  function expectedRatio() {
    const [w, h] = expectedSizeText().split("x").map((value) => Number.parseInt(value, 10));
    if (!w || !h) return null;
    return { width: w, height: h, value: w / h, label: w < h ? "9:16" : "16:9" };
  }

  function updateRatioFrame() {
    const ratio = expectedRatio();
    if (!ratio || !ratioFrame) return;
    ratioFrame.style.aspectRatio = `${ratio.width} / ${ratio.height}`;
    ratioFrame.dataset.ratio = ratio.label;
  }

  function supportedSizeForDimensions(width, height) {
    const value = `${Number(width)}x${Number(height)}`;
    return Array.from(sizeSelect.options).some((option) => option.value === value) ? value : "";
  }

  function promptCards() {
    return Array.from(promptList.querySelectorAll("[data-prompt-card]"));
  }

  function promptTextareas() {
    return Array.from(promptList.querySelectorAll('textarea[name="prompts"]'));
  }

  function refreshPromptNumbers() {
    const cards = promptCards();
    cards.forEach((card, index) => {
      const title = card.querySelector(".prompt-card-head strong");
      if (title) title.textContent = `提示词 ${index + 1}`;
      card.querySelector("textarea")?.setAttribute("aria-label", `提示词 ${index + 1}`);
      const remove = card.querySelector("[data-remove-prompt]");
      if (remove) remove.disabled = cards.length <= 1;
    });
    const count = promptTextareas().filter((item) => item.value.trim()).length;
    if (promptCountText) promptCountText.textContent = `${count} 个视频待生成`;
    if (quotaCostText) {
      const available = Number(form.dataset.availableQuota || 0);
      quotaCostText.textContent = count > available ? `预计 ${count} 次 · 当前可用 ${available} 次，额度不足` : `预计消耗 ${count} 次额度`;
      quotaCostText.style.color = count > available ? "var(--wb-error)" : "";
    }
    if (submitButton && form.dataset.busy !== "true") submitButton.textContent = count ? `生成 ${count} 个视频 ↗` : "生成视频 ↗";
    if (addPromptBtn) addPromptBtn.disabled = cards.length >= 100;
  }

  function createPromptCard(value = "") {
    const card = document.createElement("article");
    card.className = "prompt-card";
    card.dataset.promptCard = "true";
    card.innerHTML = `
      <div class="prompt-card-head">
        <strong>提示词</strong>
        <div class="inline-actions">
          <button class="ghost-btn small-btn" type="button" data-copy-prompt>复制</button>
          <button class="danger-ghost-btn small-btn" type="button" data-remove-prompt>删除</button>
        </div>
      </div>
      <textarea name="prompts" autocomplete="off" placeholder="例如：雨夜街道，镜头缓慢推进…"></textarea>
    `;
    const textarea = card.querySelector("textarea");
    if (textarea) textarea.value = value;
    return card;
  }

  function addPrompt(value = "", focus = true) {
    if (promptCards().length >= 100) { showToast("一次最多 100 条提示词。", "error"); return; }
    const card = createPromptCard(value);
    promptList.appendChild(card);
    refreshPromptNumbers();
    if (focus) card.querySelector("textarea")?.focus();
  }

  function splitImportedPrompts(text) {
    return String(text || "")
      .split(/\n\s*---\s*\n|\n\s*\n/g)
      .map((item) => item.trim())
      .filter(Boolean);
  }

  function normalizeUrl(value) {
    const text = String(value || "").trim();
    if (!text) return "";
    if (/^https?:\/\//i.test(text)) return text;
    return `https://${text}`;
  }

  function proxiedReferenceImageUrl(url) {
    const normalized = normalizeUrl(url);
    return normalized;
  }

  function setPreview(url, label = "图片链接参考图") {
    const normalized = normalizeUrl(url);
    if (!normalized) {
      if (previewImage) previewImage.removeAttribute("src");
      if (emptyText) {
        emptyText.textContent = "图片预览";
        emptyText.classList.remove("hidden");
      }
      if (imageName) imageName.textContent = "未选择参考图";
      if (imageDimensions) imageDimensions.textContent = "-";
      ratioFrame?.classList.remove("has-image", "ratio-loading", "ratio-ok", "ratio-error");
      return;
    }
    ratioFrame?.classList.add("has-image", "ratio-loading");
    ratioFrame?.classList.remove("ratio-ok", "ratio-error");
    if (previewImage) {
      previewImage.onload = () => {
        ratioFrame?.classList.remove("ratio-loading");
        if (emptyText) emptyText.classList.add("hidden");
      };
      previewImage.onerror = () => {
        ratioFrame?.classList.remove("ratio-loading", "ratio-ok");
        ratioFrame?.classList.add("ratio-error");
        if (emptyText) {
          emptyText.textContent = "无法加载";
          emptyText.classList.remove("hidden");
        }
      };
      previewImage.dataset.previewMode = "direct";
      previewImage.src = proxiedReferenceImageUrl(normalized);
    }
    if (emptyText) emptyText.classList.add("hidden");
    if (imageName) imageName.textContent = label;
    if (imageDimensions) imageDimensions.textContent = "读取中";
  }

  function ratioMatches(width, height) {
    const expected = expectedRatio();
    if (!expected) return { ok: false, message: "请选择分辨率" };
    const imageWidth = Number(width);
    const imageHeight = Number(height);
    return {
      ok: imageWidth === expected.width && imageHeight === expected.height,
      message: `需 ${expectedSizeText()}，当前 ${imageWidth}x${imageHeight}，禁止生成`,
    };
  }

  async function loadImageDimensions(url) {
    const normalized = normalizeUrl(url);
    const payload = await fetchJSON(`/app/reference-image/dimensions?url=${encodeURIComponent(normalized)}`);
    if (!payload?.width || !payload?.height) throw new Error("dimension failed");
    return { width: Number(payload.width), height: Number(payload.height) };
  }

  async function validateReferenceUrl() {
    if (["veo_omni", "wuyin_omni"].includes(selectedProvider())) { latestImageCheckToken++; return Boolean(secondsSelect.value && sizeSelect.value); }
    syncImageConfirmations();
    updateRatioFrame();
    const selectedOption = presetSelect?.selectedOptions?.[0];
    const url = normalizeUrl(urlInput?.value || selectedOption?.dataset.url || "");
    const token = ++latestImageCheckToken;

    if (!url) {
      setPreview("");
      if (!secondsSelect.value) updateHint("请选择模型。", true);
      else if (!sizeSelect.value) updateHint("请选择分辨率。", true);
      else updateHint("未使用参考图。", false);
      return Boolean(secondsSelect.value && sizeSelect.value);
    }

    const label = selectedOption?.value ? selectedOption.textContent.trim() : "图片链接参考图";
    setPreview(url, label);

    if (!selectedOption?.value && imageConfirmations.get(urlInput)?.checked) {
      ratioFrame?.classList.remove('ratio-loading','ratio-error','ratio-ok');
      if (imageDimensions) imageDimensions.textContent = '已确认可用 · 未检查尺寸';
      updateHint('已跳过本机读取检查，将直接提交图片链接。');
      return Boolean(secondsSelect.value && sizeSelect.value);
    }
    let dimensions = null;
    const dataWidth = Number.parseInt(selectedOption?.dataset.width || "", 10);
    const dataHeight = Number.parseInt(selectedOption?.dataset.height || "", 10);
    if (selectedOption?.value && dataWidth && dataHeight && selectedOption.dataset.url === url) {
      dimensions = { width: dataWidth, height: dataHeight };
    } else {
      updateHint("读取参考图...", false);
      try {
        dimensions = await loadImageDimensions(url);
      } catch (error) {
        if (token !== latestImageCheckToken) return false;
        ratioFrame?.classList.remove("ratio-loading", "ratio-ok");
        ratioFrame?.classList.add("ratio-error");
        const message = error?.message || "参考图无法加载。";
        if (imageDimensions) imageDimensions.textContent = "无法读取";
        updateHint(message, true);
        return false;
      }
    }
    if (token !== latestImageCheckToken) return false;
    if (!sizeSelect.value) {
      const detectedSize = supportedSizeForDimensions(dimensions.width, dimensions.height);
      if (detectedSize) {
        sizeSelect.value = detectedSize;
        updateRatioFrame();
      }
    }
    if (!secondsSelect.value) {
      if (imageDimensions) imageDimensions.textContent = `${dimensions.width}x${dimensions.height}`;
      ratioFrame?.classList.remove("ratio-loading", "ratio-ok", "ratio-error");
      updateHint("请选择模型。", true);
      return false;
    }
    if (!sizeSelect.value) {
      if (imageDimensions) imageDimensions.textContent = `${dimensions.width}x${dimensions.height}`;
      ratioFrame?.classList.remove("ratio-loading", "ratio-ok");
      ratioFrame?.classList.add("ratio-error");
      updateHint("请选择分辨率。", true);
      return false;
    }
    const matched = ratioMatches(dimensions.width, dimensions.height);
    if (imageDimensions) imageDimensions.textContent = matched.ok ? `${dimensions.width}x${dimensions.height} 匹配` : matched.message;
    ratioFrame?.classList.remove("ratio-loading");
    ratioFrame?.classList.toggle("ratio-ok", matched.ok);
    ratioFrame?.classList.toggle("ratio-error", !matched.ok);
    updateHint(matched.ok ? "参考图匹配。" : `参考图比例不符，${matched.message}`, !matched.ok);
    return matched.ok;
  }

  function scheduleReferenceValidation(delay = 520) {
    if (referenceUrlTimer) clearTimeout(referenceUrlTimer);
    referenceUrlTimer = setTimeout(() => {
      void validateReferenceUrl();
    }, delay);
  }

  function syncReferenceUrl(delay = 520) {
    if (presetSelect && urlInput?.value) presetSelect.value = "";
    syncImageConfirmations();
    const rawUrl = urlInput?.value || presetSelect?.selectedOptions?.[0]?.dataset.url || "";
    lastReferenceUrlValue = normalizeUrl(rawUrl);
    setPreview(rawUrl);
    scheduleReferenceValidation(delay);
  }

  function watchReferenceUrlValue() {
    const current = normalizeUrl(urlInput?.value || presetSelect?.selectedOptions?.[0]?.dataset.url || "");
    if (current !== lastReferenceUrlValue) {
      syncReferenceUrl(120);
    }
  }

  presetSelect?.addEventListener("change", () => {
    const option = presetSelect.selectedOptions?.[0];
    if (urlInput) urlInput.value = option?.dataset.url || "";
    void validateReferenceUrl();
  });

  urlInput?.addEventListener("input", () => {
    syncReferenceUrl();
  });
  urlInput?.addEventListener("change", () => syncReferenceUrl(80));
  urlInput?.addEventListener("paste", () => setTimeout(() => syncReferenceUrl(80), 0));
  urlInput?.addEventListener("blur", () => void validateReferenceUrl());
  sizeSelect.addEventListener("change", () => void validateReferenceUrl());
  secondsSelect.addEventListener("change", () => void validateReferenceUrl());
  modelSelect?.addEventListener("change", () => {
    syncModelSeconds();
    void validateReferenceUrl();
  });
  omniMaterialCard?.addEventListener("change", (event) => {
    if (event.target.matches('input[name="omni_reference_preset_ids"]')) {
      const maximum = omniMaxImages();
      if (omniImageCount() > maximum) {
        event.target.checked = false;
        showToast(`当前渠道最多支持 ${maximum} 张参考图。`, "error");
      }
    }
    refreshOmniCount();
  });
  omniImageUrlList?.addEventListener("input", () => refreshOmniCount());
  omniImageUrlList?.addEventListener("click", (event) => {
    const remove = event.target.closest(".omni-remove-image");
    if (!remove) return;
    const row = remove.closest(".omni-image-url-row");
    const rows = omniImageUrlList.querySelectorAll(".omni-image-url-row");
    if (rows.length <= 1) {
      const input = row?.querySelector("input");
      if (input) input.value = "";
    } else {
      row?.remove();
    }
    refreshOmniCount();
  });
  omniAddImage?.addEventListener("click", addOmniImageRow);
  // Input/change/paste events already cover reference updates; no perpetual timer.
  form.querySelectorAll('input[name="aspect_choice"]').forEach(input => input.addEventListener("change", () => {
    sizeSelect.value = input.value; sizeSelect.dispatchEvent(new Event("change", {bubbles:true}));
  }));
  const updateSpec = () => {
    form.querySelectorAll('input[name="aspect_choice"]').forEach(input => { input.checked = input.value === sizeSelect.value; });
    const spec = document.getElementById("studio-spec-summary");
    if (spec) spec.textContent = secondsSelect.value ? `${secondsSelect.value} 秒 / ${sizeSelect.value.replace("x", " × ")}` : "选择模型后显示生成时长";
  };
  sizeSelect.addEventListener("change",updateSpec); modelSelect?.addEventListener("change",updateSpec);


  addPromptBtn?.addEventListener("click", (event) => {
    event.preventDefault();
    addPrompt("", true);
  });
  promptList.addEventListener("input", (event) => {
    if (event.target.matches('textarea[name="prompts"]')) refreshPromptNumbers();
  });
  promptList.addEventListener("click", (event) => {
    const copyBtn = event.target.closest("[data-copy-prompt]");
    const removeBtn = event.target.closest("[data-remove-prompt]");
    if (copyBtn) {
      event.preventDefault();
      const card = copyBtn.closest("[data-prompt-card]");
      const textarea = card?.querySelector('textarea[name="prompts"]');
      addPrompt(textarea?.value || "", true);
    }
    if (removeBtn) {
      event.preventDefault();
      const cards = promptCards();
      if (cards.length <= 1) return;
      removeBtn.closest("[data-prompt-card]")?.remove();
      refreshPromptNumbers();
    }
  });

  importToggle?.addEventListener("click", () => { importBox?.classList.toggle("hidden"); importToggle.setAttribute("aria-expanded", String(!importBox.classList.contains("hidden"))); if (!importBox.classList.contains("hidden")) importTextarea?.focus(); });
  importCancel?.addEventListener("click", () => importBox?.classList.add("hidden"));
  importApply?.addEventListener("click", async () => {
    const items = splitImportedPrompts(importTextarea?.value || "");
    if (!items.length) {
      showToast("请先输入要导入的提示词。", "error");
      return;
    }
    const replaceExisting = document.getElementById("batch-import-mode")?.value === "replace";
    const existing = promptTextareas().filter(item => item.value.trim());
    if (items.length + (replaceExisting ? 0 : existing.length) > 100) { showToast("合计超过 100 条，请减少导入数量；当前内容未改变。", "error"); return; }
    if (replaceExisting && existing.length && !await SoraUI.confirm("替换当前全部提示词？此操作会清除已填写内容。")) return;
    if (replaceExisting) promptList.replaceChildren();
    else promptCards().filter(card => !card.querySelector("textarea").value.trim()).forEach(card => card.remove());
    items.forEach((item) => addPrompt(item, false));
    importToggle?.setAttribute("aria-expanded", "false");
    importBox?.classList.add("hidden");
    if (importTextarea) importTextarea.value = "";
    showToast(`已导入 ${items.length} 条提示词`, "info");
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (form.dataset.busy === "true") return;
    form.dataset.busy = "true";
    const originalText = submitButton?.textContent || "生成视频";
    try {
      document.getElementById("studio-form-error")?.classList.add("hidden");
      if (!form.reportValidity()) return;
      const prompts = promptTextareas().map(item => item.value.trim()).filter(Boolean);
      if (!prompts.length) { promptTextareas()[0]?.focus(); throw new Error("请至少填写一条提示词。"); }
      if (prompts.length > 100) throw new Error("一次最多创建 100 个任务。");
      if (prompts.length > Number(form.dataset.availableQuota || 0)) throw new Error("当前可用额度不足，请减少任务数量或前往额度页申请。");
      if (!validateOmniMaterials()) return;
      if (!await validateReferenceUrl()) throw new Error(hint.textContent || "请检查模型和参考素材。");
      if (!await SoraUI.confirm(`将创建 ${prompts.length} 个视频，预计消耗 ${prompts.length} 次额度。`, {title:"提交本批次",label:"确认生成"})) return;
      if (submitButton) { submitButton.disabled = true; submitButton.textContent = "正在提交…"; submitButton.setAttribute("aria-busy", "true"); }
      const data = new FormData(form);
      data.delete("prompts"); prompts.forEach(prompt => data.append("prompts",prompt));
      const response = await fetchJSON(form.dataset.asyncFormdata, {method:"POST",body:data});
      if (!response) return;
      document.dispatchEvent(new CustomEvent('lumora:saved',{detail:{form}}));window.location.assign(response.target || '/app/jobs/page');
    } catch (error) { SoraUI.formError(form,error); }
    finally {
      delete form.dataset.busy;
      if (submitButton) { submitButton.disabled = !modelSelect?.options.length || modelSelect.options.length <= 1; submitButton.innerHTML = originalText; submitButton.removeAttribute("aria-busy"); }
      refreshPromptNumbers();
    }
  });

  refreshPromptNumbers();
  syncModelSeconds();
  updateRatioFrame();
  updateSpec();
  if (normalizeUrl(urlInput?.value || presetSelect?.selectedOptions?.[0]?.dataset.url || "")) {
    syncReferenceUrl(80);
  } else {
    lastReferenceUrlValue = "";
    setPreview("");
    updateHint("选择模型、分辨率后创建。", false);
  }
}
function initPlazaPage() {
  if (!window.PLAZA_PAGE) return;
  const modal = document.getElementById("plaza-modal");
  const player = document.getElementById("plaza-player");
  const creator = document.getElementById("plaza-creator");
  const productName = document.getElementById("plaza-product-name");
  const regionName = document.getElementById("plaza-region-name");
  const size = document.getElementById("plaza-size");
  const seconds = document.getElementById("plaza-seconds");
  const model = document.getElementById("plaza-model");
  const createdAt = document.getElementById("plaza-created-at");
  const prompt = document.getElementById("plaza-prompt");
  const copyPrompt = document.getElementById("plaza-copy-prompt");
  const protectionRow = document.getElementById("plaza-protection-row");

  let modalEpoch=0,previewEpoch=0;
  async function openModal(jobId,origin) {
    const request=++modalEpoch;
    let payload;
    try {payload=await fetchJSON(`/app/plaza/jobs/${jobId}`);} catch(error) {if(request!==modalEpoch)return;throw error;}
    if(request!==modalEpoch)return;
    creator.textContent = payload.creator || "-";
    productName.textContent = payload.product_name || "-";
    regionName.textContent = payload.region_name || "-";
    size.textContent = payload.size || "-";
    seconds.textContent = payload.seconds ? `${payload.seconds} 秒` : "-";
    if (model) model.textContent = payload.model || "-";
    createdAt.textContent = payload.created_at || "-";
    prompt.textContent = payload.prompt || "-";
    if (copyPrompt) copyPrompt.dataset.copyText = payload.prompt || "";
    protectionRow?.classList.toggle("hidden", !payload.is_private_protected);
    player.src = payload.output_file ? `/app/files/${payload.output_file.id}/stream` : "";
    SoraUI.setModalOrigin(modal,origin);
    modal.classList.remove("hidden");
    document.body.style.overflow = "hidden";
  }

  function closeModal() {
    modalEpoch++;
    modal.classList.add("hidden");
    player.pause();
    player.removeAttribute("src");
    player.load();
    document.body.style.overflow = "";
  }

  function setPreviewButtons(shell, isPlaying) {
    const card = shell.closest(".plaza-card");
    if (!card) return;
    card.querySelectorAll(".plaza-preview-trigger").forEach((element) => {
      if (element.matches("button") && !element.classList.contains("plaza-video-shell")) {
        element.textContent = isPlaying ? "暂停预览" : "播放预览";
      }
    });
  }

  function stopInlinePreview(shell) {
    const video = shell.querySelector(".plaza-inline-video");
    const poster = shell.querySelector(".plaza-poster");
    if (!video || !poster) return;
    if(video.hasAttribute("src")) {video.pause();video.removeAttribute("src");video.load();}
    video.dataset.loaded = "false";
    video.classList.add("hidden");
    poster.classList.remove("hidden");
    setPreviewButtons(shell, false);
  }

  async function startInlinePreview(trigger) {
    const request=++previewEpoch;
    const shell = trigger.classList.contains("plaza-video-shell")
      ? trigger
      : trigger.closest(".plaza-card")?.querySelector(".plaza-video-shell");
    if (!shell) return;

    document.querySelectorAll(".plaza-video-shell").forEach((item) => {
      if (item !== shell) stopInlinePreview(item);
    });

    const video = shell.querySelector(".plaza-inline-video");
    const poster = shell.querySelector(".plaza-poster");
    const streamUrl = trigger.dataset.streamUrl || shell.dataset.streamUrl;
    if (!video || !poster || !streamUrl) return;

    if (!video.classList.contains("hidden") && !video.paused) {
      stopInlinePreview(shell);
      return;
    }

    if (video.dataset.loaded !== "true" || !video.currentSrc) {
      video.src = streamUrl;
      video.dataset.loaded = "true";
    }
    video.muted = false;
    video.volume = 1;
    poster.classList.add("hidden");
    video.classList.remove("hidden");
    try {
      await video.play();
      if(request!==previewEpoch)return;
      setPreviewButtons(shell, true);
    } catch (_) {
      if(request!==previewEpoch)return;
      poster.classList.remove("hidden");
      video.classList.add("hidden");
      setPreviewButtons(shell, false);
      showToast("当前预览暂时无法播放", "error");
    }
  }

  document.querySelectorAll(".plaza-preview-trigger").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await startInlinePreview(button);
      } catch (error) {
        showToast(error.message || "加载预览失败", "error");
      }
    });
  });

  document.querySelectorAll(".plaza-open-btn").forEach((button) => {
    button.addEventListener("click", async () => {
      if(button.disabled)return;
      const label=button.textContent;button.disabled=true;button.textContent="正在打开…";button.setAttribute("aria-busy","true");
      try {
        await openModal(button.dataset.jobId,button);
      } catch (error) {
        showToast(error.message || "打开作品详情失败", "error");
      } finally {button.disabled=false;button.textContent=label;button.removeAttribute("aria-busy");}
    });
  });

  document.addEventListener("visibilitychange",()=>{
    if(!document.hidden)return;
    previewEpoch++;
    document.querySelectorAll(".plaza-inline-video:not(.hidden)").forEach(video=>stopInlinePreview(video.closest(".plaza-video-shell")));
  });
  document.querySelectorAll("[data-close-plaza]").forEach((button) => {
    button.addEventListener("click", closeModal);
  });
}
function initLibraryStarToggles() {
  document.querySelectorAll("[data-toggle-star]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      const jobId = button.dataset.toggleStar;
      if (!jobId) return;
      button.disabled = true;
      try {
        const payload = await fetchJSON(`/app/jobs/${jobId}/toggle-star`, { method: "POST" });
        if (!payload) return;
        const isStarred = Boolean(payload.is_starred);
        const card = button.closest(".library-card");
        button.classList.toggle("active", isStarred);
        const icon = button.querySelector(".star-icon");
        const text = button.querySelector(".star-text");
        if (icon) icon.textContent = "";
        if (text) text.textContent = isStarred ? "已收藏" : "收藏";
        if (!icon && !text) button.textContent = isStarred ? "已收藏" : "收藏";
        button.setAttribute("aria-label", isStarred ? "取消收藏" : "收藏优质素材");
        button.setAttribute("title", isStarred ? "取消收藏" : "收藏优质素材");
        if (card) card.classList.toggle("is-starred", isStarred);
        showToast(isStarred ? "已收藏为优质素材" : "已取消收藏", "info");
        if (!isStarred && window.LIBRARY_STARRED_ONLY && card) {
          card.remove();
          const grid = document.querySelector(".plaza-grid");
          if (grid && !grid.querySelector(".library-card")) {
            const empty = document.createElement("div");
            empty.className = "empty-state compact-empty";
            empty.textContent = "暂无收藏素材";
            grid.replaceWith(empty);
          }
        }
      } catch (error) {
        showToast(error.message || "收藏操作失败", "error");
      } finally {
        button.disabled = false;
      }
    });
  });
}

function initLibraryProtectionToggles() {
  document.querySelectorAll("[data-toggle-protection]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      const jobId = button.dataset.toggleProtection;
      if (!jobId) return;
      button.disabled = true;
      try {
        const payload = await fetchJSON(`/app/jobs/${jobId}/toggle-private-protection`, { method: "POST" });
        if (!payload) return;
        const isProtected = Boolean(payload.is_private_protected);
        const card = button.closest(".library-card");
        button.classList.toggle("active", isProtected);
        const text = button.querySelector(".protection-text");
        if (text) text.textContent = isProtected ? "取消保护" : "自用保护";
        else button.textContent = isProtected ? "取消保护" : "自用保护";
        button.setAttribute("aria-label", isProtected ? "取消自用保护" : "标记自用保护");
        button.setAttribute("title", isProtected ? "取消自用保护" : "标记自用保护");
        if (card) {
          card.classList.toggle("is-protected", isProtected);
          let badge = card.querySelector(".protection-badge");
          const metaLeft = card.querySelector(".library-meta-left");
          if (isProtected && !badge && metaLeft) {
            badge = document.createElement("span");
            badge.className = "protection-badge";
            badge.textContent = "自用保护";
            metaLeft.insertBefore(badge, metaLeft.querySelector(".muted"));
          } else if (!isProtected && badge) {
            badge.remove();
          }
          let ribbon = card.querySelector(".protected-ribbon");
          const poster = card.querySelector(".plaza-poster");
          if (isProtected && !ribbon && poster) {
            ribbon = document.createElement("div");
            ribbon.className = "protected-ribbon";
            ribbon.textContent = "自用保护";
            poster.prepend(ribbon);
          } else if (!isProtected && ribbon) {
            ribbon.remove();
          }
        }
        showToast(isProtected ? "已开启自用保护提示" : "已取消自用保护", "info");
      } catch (error) {
        showToast(error.message || "保护设置失败", "error");
      } finally {
        button.disabled = false;
      }
    });
  });
}

function initLibraryBulkDownload() {
  const toolbar = document.querySelector("[data-library-bulk-toolbar]");
  if (!toolbar) return;
  const selectAll = document.getElementById("library-select-all");
  const clearBtn = document.getElementById("library-clear-selection");
  const downloadBtn = document.getElementById("library-download-selected");
  const countEl = document.getElementById("library-selected-count");

  function allBoxes() {
    return Array.from(document.querySelectorAll(".library-select-checkbox"));
  }

  function selectedBoxes() {
    return allBoxes().filter((item) => item.checked);
  }

  function syncState() {
    const checkboxes = allBoxes();
    const selected = selectedBoxes();
    if (countEl) countEl.textContent = `已选择 ${selected.length} 个`;
    if (downloadBtn) downloadBtn.disabled = selected.length === 0;
    if (selectAll) {
      selectAll.checked = checkboxes.length > 0 && selected.length === checkboxes.length;
      selectAll.indeterminate = selected.length > 0 && selected.length < checkboxes.length;
    }
    checkboxes.forEach((box) => {
      box.closest(".library-card")?.classList.toggle("is-selected", box.checked);
      box.closest(".library-card-check")?.classList.toggle("is-checked", box.checked);
    });
  }

  document.addEventListener("change", (event) => {
    if (event.target.matches(".library-select-checkbox")) syncState();
  });
  selectAll?.addEventListener("change", () => {
    allBoxes().forEach((box) => {
      box.checked = Boolean(selectAll.checked);
    });
    syncState();
  });
  clearBtn?.addEventListener("click", () => {
    allBoxes().forEach((box) => {
      box.checked = false;
    });
    syncState();
  });
  downloadBtn?.addEventListener("click", () => {
    const ids = selectedBoxes().map((box) => box.value).filter(Boolean);
    if (!ids.length) {
      showToast("请选择要下载的作品。", "error");
      return;
    }
    const url = `/app/library/bulk-download?job_ids=${encodeURIComponent(ids.join(","))}`;
    window.location.assign(url);
    showToast(`正在打包 ${ids.length} 个视频`, "info");
  });
  syncState();
}

function initBatchResultPage() {
  if (!window.BATCH_DATA_ENDPOINT) return;
  let timer = null, failures = 0, inFlight = false, active = true;
  const state = document.getElementById("batch-refresh-state");
  const setText = (id,value) => { const el = document.getElementById(id); if (el) el.textContent = value; };
  async function refresh() {
    if (inFlight || document.hidden) return;
    inFlight = true;
    try {
      const payload = await fetchJSON(window.BATCH_DATA_ENDPOINT);
      if (!payload) return;
      failures = 0;
      const batch = payload.batch, jobs = payload.jobs;
      setText("batch-state",batch.state_label); setText("batch-summary",batch.summary);
      setText("batch-completed",batch.completed_count); setText("batch-active",batch.active_count); setText("batch-failed",batch.failed_count);
      const ids = new Set(jobs.map(job => String(job.id)));
      document.querySelectorAll("[data-batch-job]").forEach(row => { if (!ids.has(row.dataset.batchJob)) row.remove(); });
      jobs.forEach(job => {
        const row = document.querySelector(`[data-batch-job="${Number(job.id)}"]`);
        if (!row) return;
        const badge = row.querySelector("[data-job-status]"); badge.textContent = job.status_label; badge.className = `badge status-${job.status}`;
        row.querySelector("[data-job-queue]").textContent = job.queue_text;
        row.querySelector("[data-job-progress]").textContent = `${Math.max(0,Math.min(100,job.progress || 0))}%`;
        const download = row.querySelector("[data-job-download]");
        if (download) { download.classList.toggle("hidden", !job.output_file || job.status !== "completed"); if (job.output_file) download.href = `/app/files/${job.output_file.id}/download`; }
      });
      const zip = document.getElementById("batch-download");
      zip?.classList.toggle("hidden", !batch.downloadable_count);
      document.getElementById("batch-download-empty")?.classList.toggle("hidden", !!batch.downloadable_count);
      if (zip) zip.textContent = `下载已完成 ${batch.downloadable_count} 个`;
      active = batch.active_count > 0;
      if (state) state.textContent = active ? "自动更新中" : "本批次已结束自动处理";
    } catch (error) { failures++; if (state) state.textContent = "更新暂时失败，将自动重试"; }
    finally { inFlight = false; schedule(); }
  }
  function schedule() { clearTimeout(timer); if (!document.hidden && (active || failures)) timer = setTimeout(refresh, Math.min(8000 * 2 ** failures,60000)); }
  document.addEventListener("visibilitychange", () => { clearTimeout(timer); if (!document.hidden) { active = true; void refresh(); } });
  window.addEventListener("focus", () => { if (!document.hidden && !inFlight) void refresh(); });
  void refresh();
}

function initActionPostButtons() {
  document.querySelectorAll("[data-action-post]").forEach((button) => {
    button.addEventListener("click", async () => {
      const endpoint = button.dataset.actionPost;
      if (!endpoint) return;
      const confirmText = button.dataset.confirm;
      if (confirmText && !await SoraUI.confirm(confirmText)) return;
      const originalText = button.textContent;
      button.disabled = true;
      button.textContent = button.dataset.loadingText || "处理中…";
      try {
        await fetchJSON(endpoint, { method: "POST" });
        showToast(button.dataset.successMessage || "操作已提交", "info");
        window.location.reload();
      } catch (error) {
        showToast(error.message || "操作失败", "error");
      } finally {
        button.disabled = false;
        button.textContent = originalText;
      }
    });
  });
}

function initUsageMonthlyPage() {
  if (!window.USAGE_EDIT_ENABLED) return;
  const modal = document.getElementById("usage-modal");
  const userIdInput = document.getElementById("usage-user-id");
  const usernameInput = document.getElementById("usage-username");
  const dateInput = document.getElementById("usage-date");
  const realInput = document.getElementById("usage-real");
  const displayInput = document.getElementById("usage-display");
  const deleteUserId = document.getElementById("usage-delete-user-id");
  const deleteDate = document.getElementById("usage-delete-date");
  document.querySelector(".usage-table")?.addEventListener("click", event => {
      const button=event.target.closest(".usage-edit-btn");if(!button)return;
      SoraUI.setModalOrigin(modal,button);
      userIdInput.value = button.dataset.userId || "";
      usernameInput.value = button.dataset.username || "";
      dateInput.value = button.dataset.date || "";
      realInput.value = button.dataset.real || "0";
      displayInput.value = button.dataset.display || "0";
      deleteUserId.value = button.dataset.userId || "";
      deleteDate.value = button.dataset.date || "";
      modal?.classList.remove("hidden");
  });
  document.querySelectorAll("[data-close-usage]").forEach((button) => {
    button.addEventListener("click", () => modal?.classList.add("hidden"));
  });
}

function initProviderKeyForms() {
  document.querySelectorAll(".provider-key-config-form").forEach((form) => {
    const providerSelect = form.querySelector('select[name="provider_name"]');
    const fields = Array.from(form.querySelectorAll("[data-provider-model-field]"));
    const baseUrlInput = form.querySelector('input[name="api_base_url"]');
    if (!providerSelect || !fields.length) return;
    const defaultBaseUrls = {
      sora_api: "https://niubi.zeabur.app",
      wuyin_omni: "https://api.wuyinkeji.com",
    };
    const syncFields = (updateBaseUrl = false) => {
      const provider = providerSelect.value || "sora_api";
      fields.forEach((field) => {
        const providers = String(field.dataset.providerModelField || "").split(/\s+/).filter(Boolean);
        field.classList.toggle("hidden", !providers.includes(provider));
      });
      if (updateBaseUrl && baseUrlInput && defaultBaseUrls[provider]) {
        baseUrlInput.value = defaultBaseUrls[provider];
      }
    };
    providerSelect.addEventListener("change", () => syncFields(true));
    syncFields();
  });
}

function initPerPagePreference() {
  const forms = Array.from(document.querySelectorAll("[data-per-page-form]"));
  if (!forms.length) return;
  const params = new URLSearchParams(window.location.search);
  forms.forEach((form) => {
    const select = form.querySelector("[data-per-page-select]");
    if (!select) return;
    const storageKey = form.dataset.perPageStorageKey || "";
    if (storageKey && !params.has("per_page")) {
      const stored = localStorage.getItem(storageKey);
      if (stored && Array.from(select.options).some((option) => option.value === stored)) {
        params.set("per_page", stored);
        params.set("page", "1");
        window.location.search = params.toString();
        return;
      }
    }
    select.addEventListener("change", () => {
      if (storageKey) localStorage.setItem(storageKey, select.value);
      form.requestSubmit ? form.requestSubmit() : form.submit();
    });
    if (storageKey && params.has("per_page")) localStorage.setItem(storageKey, select.value);
  });
}

function safeInit(name, fn) {
  try {
    fn();
  } catch (error) {
    console.error(`[init:${name}]`, error);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  safeInit("toasts", initToasts);
  safeInit("loginMode", initLoginModeSwitch);
  safeInit("copyText", initCopyTextButtons);
  safeInit("asyncForms", initAsyncForms);
  safeInit("jobDetail", initJobDetailPage);
  safeInit("tabs", initTabs);
  safeInit("rowMenus", initRowMenus);
  safeInit("toggleEdit", initToggleEditBlocks);
  safeInit("usernameConfirm", initUsernameConfirmForms);
  safeInit("createJobForm", initCreateJobForm);
  safeInit("plaza", initPlazaPage);
  safeInit("usageMonthly", initUsageMonthlyPage);
  safeInit("providerKeyForms", initProviderKeyForms);
  safeInit("actionPost", initActionPostButtons);
  safeInit("libraryStar", initLibraryStarToggles);
  safeInit("libraryProtection", initLibraryProtectionToggles);
  safeInit("libraryBulkDownload", initLibraryBulkDownload);
  safeInit("batchResult", initBatchResultPage);
  safeInit("perPagePreference", initPerPagePreference);
});



