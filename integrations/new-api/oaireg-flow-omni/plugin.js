// New API task-plugin API v1. No network calls are performed inside hooks.
export const meta = {
  apiVersion: 1,
  key: "oaireg-flow-omni",
  name: "oaireg flow omni 专用插件",
  version: "1.1.0",
  author: { name: "Lumora" },
  description: { en: "Flow Omni JSON passthrough for text, image and video reference generation.", zh: "保留 Flow Omni 的画幅、参考图、参考视频及扩展参数。" },
  models: ["flow-omni-1.1-flash"],
  // Bind a dedicated task-plugin channel; do not take over OpenAI channel type 1.
  fetchMode: "per_task",
  upstreams: ["vendor"],
  protocols: ["openai_video"],
  // Flow is billed per request. Mode can be used by an administrator's pricing expression.
  // Do not multiply a per-request price by the approximate eight-second duration.
  usageSchema: {
    requests: { type: "number", unit: "count", description: { en: "Generations", zh: "生成次数" }, unitLabel: { en: "request", zh: "次" } },
    mode: { enum: ["text-to-video", "image-to-video", "video-to-video"], description: { en: "Generation mode", zh: "生成方式" }, enumLabels: { "text-to-video": { en: "Text to video", zh: "文生视频" }, "image-to-video": { en: "Image to video", zh: "图生视频" }, "video-to-video": { en: "Video editing", zh: "视频编辑" } } },
  },
};

function requestBody(value, model) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("JSON object required");
  if (!meta.models.includes(model)) throw new Error("unsupported Flow Omni model");
  if (typeof value.prompt !== "string" || !value.prompt.trim()) throw new Error("prompt is required");
  if (value.aspect_ratio !== undefined && !["9:16", "16:9"].includes(value.aspect_ratio))
    throw new Error("aspect_ratio must be 9:16 or 16:9");
  if (value.resolution !== undefined && value.resolution !== "720p") throw new Error("resolution must be 720p");
  if (value.size !== undefined && (typeof value.size !== "string" || !/^[1-9][0-9]*x[1-9][0-9]*$/.test(value.size)))
    throw new Error("size must use positive WxH dimensions");
  if (value.image_url !== undefined) throw new Error("Flow uses image or images, not image_url");
  for (const key of ["image", "input_reference"]) {
    if (value[key] !== undefined && (typeof value[key] !== "string" || !value[key].trim()))
      throw new Error(key + " must be a non-empty string");
  }
  if (value.images !== undefined && (!Array.isArray(value.images) || value.images.some(function (x) { return typeof x !== "string" || !x.trim(); })))
    throw new Error("images must be an array of non-empty strings");
  // The vendor recommends <=6 images, but does not document a hard limit.
  // Preserve size/aspect_ratio together: the vendor gives size precedence.
  return Object.assign({}, value, { model: model });
}

function mode(req) {
  if (req.input_reference) return "video-to-video";
  return req.image || (req.images || []).length ? "image-to-video" : "text-to-video";
}

function outputURL(body) {
  if (!body || body.status !== "completed") return "";
  const first = Array.isArray(body.data) ? body.data[0] : null;
  const candidates = [body.video_url, first && first.url, body.metadata && body.metadata.url];
  for (const url of candidates) {
    if (typeof url === "string" && /^https?:\/\/[^\s]+$/.test(url)) return url;
  }
  return "";
}

function endpoint(ctx, suffix) {
  return String(ctx.baseUrl || "").replace(/\/+$/, "") + "/v1/videos" + suffix;
}

export function buildSubmitRequest(ctx) {
  if ((ctx.files || []).length) throw new Error("use JSON image, images or input_reference, not file uploads");
  return {
    url: endpoint(ctx, ""),
    method: "POST",
    headers: { Authorization: "Bearer " + ctx.apiKey, "Content-Type": "application/json" },
    body: requestBody(ctx.requestBody, ctx.upstreamModel || ctx.model),
  };
}

export function parseSubmitResponse(ctx, resp) {
  const body = resp.body || {};
  const id = body.id || body.task_id;
  if (typeof id !== "string" || !id) throw new Error("upstream task id is missing");
  return { taskId: id, taskData: body };
}

export function buildQueryRequest(ctx) {
  return { url: endpoint(ctx, "/" + encodeURIComponent(ctx.taskId)), method: "GET", headers: { Authorization: "Bearer " + ctx.apiKey } };
}

export function parseTaskResult(ctx, body) {
  const statuses = { queued: "QUEUED", pending: "QUEUED", processing: "IN_PROGRESS", in_progress: "IN_PROGRESS", completed: "SUCCESS", failed: "FAILURE", cancelled: "FAILURE", canceled: "FAILURE" };
  const result = { status: statuses[body.status] || "UNKNOWN" };
  if (result.status === "UNKNOWN") result.reason = "unrecognized status: " + String(body.status || "");
  if (["QUEUED", "IN_PROGRESS"].includes(result.status) && Number.isFinite(Number(body.progress)) && Number(body.progress) > 0)
    result.progress = Math.min(99, Number(body.progress)) + "%";
  if (result.status === "FAILURE") {
    result.reason = typeof body.error === "string" ? body.error : body.error && body.error.message ? body.error.message : "task failed";
  }
  if (result.status === "SUCCESS") {
    const url = outputURL(body);
    if (!url) return { status: "UNKNOWN", reason: "completed response is missing a video URL" };
    result.progress = "100%";
    result.url = url;
    result.remoteUrl = url;
  }
  return result;
}

export function extractUsage(ctx) {
  return { requests: 1, mode: mode(ctx.requestBody || {}) };
}

export function extractUsageOnComplete(task, result, body) {
  // Never infer a new charge from vendor duration, progress, or poll count.
  return { requests: 1 };
}

export function listArtifacts(task) {
  return task.status === "SUCCESS" && outputURL(task.data) ? [{ key: "video", type: "video" }] : [];
}

export function buildContentRequest(ctx) {
  if (ctx.artifactKey !== "video" || ctx.status !== "SUCCESS") throw new Error("artifact_not_found");
  const url = outputURL(ctx.data);
  if (!url) throw new Error("video URL is unavailable");
  const method = (ctx.clientRequest || {}).method || "GET";
  if (!["GET", "HEAD"].includes(method)) throw new Error("content only supports GET or HEAD");
  // Download URLs are a separate origin. Never forward the channel credential.
  return { url: url, method: method, credentialless: true };
}

export const protocols = {
  openai_video: {
    decodeRequest: function (ctx) {
      if (!ctx.body || ctx.body.kind !== "json") throw new Error("JSON body required; use image, images or input_reference");
      const req = requestBody(ctx.body.value, ctx.model);
      return { kind: "submit", model: ctx.model, action: mode(req).replace(/-/g, "_"), requestBody: req };
    },
    render: function (ctx, task) {
      // New API manages the public task identity; preserve the vendor response.
      if (task.data && typeof task.data === "object" && !Array.isArray(task.data)) {
        const data = Object.assign({}, task.data);
        if (["queued", "pending", "processing", "in_progress"].includes(data.status) && Number(data.progress) >= 100) data.progress = 99;
        return data;
      }
      const states = { NOT_START: "queued", SUBMITTED: "queued", QUEUED: "queued", IN_PROGRESS: "in_progress", SUCCESS: "completed", FAILURE: "failed" };
      const result = { id: task.task_id, object: "video", model: (task.properties || {}).origin_model_name || "", status: states[task.status] || "unknown", progress: Number(String(task.progress || "0").replace("%", "")), created_at: Number(task.created_at || 0) };
      if (task.status === "FAILURE") result.error = { code: "video_generation_failed", message: task.fail_reason || "The video generation task failed." };
      return result;
    },
  },
};
