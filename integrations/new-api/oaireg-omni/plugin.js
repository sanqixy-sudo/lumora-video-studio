// New API task-plugin API v1. No network calls are performed inside hooks.
export const meta = {
  apiVersion: 1,
  key: "oaireg-omni",
  name: "oaireg omni 专用插件",
  version: "1.1.0",
  author: { name: "Lumora" },
  description: { en: "Preserve Omni aspect ratio, reference images and JSON extension fields.", zh: "保留 Omni 的画幅、参考图及扩展 JSON 参数。" },
  models: ["omni-fast", "omni-fast-no-water"],
  // Bind a dedicated task-plugin channel; do not take over OpenAI channel type 1.
  fetchMode: "per_task",
  upstreams: ["vendor"],
  protocols: ["openai_video"],
  // A generation is one billable request, regardless of duration or polling.
  usageSchema: {
    requests: { type: "number", unit: "count", description: { en: "Generations", zh: "生成次数" }, unitLabel: { en: "request", zh: "次" } },
  },
};

function requestBody(value, model) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("JSON object required");
  if (!meta.models.includes(model)) throw new Error("unsupported Omni model");
  if (typeof value.prompt !== "string" || !value.prompt.trim()) throw new Error("prompt is required");
  if (value.aspect_ratio !== undefined && !["9:16", "16:9"].includes(value.aspect_ratio))
    throw new Error("aspect_ratio must be 9:16 or 16:9");
  if (value.image_url !== undefined && (typeof value.image_url !== "string" || !value.image_url.trim()))
    throw new Error("image_url must be a non-empty string");
  if (value.images !== undefined && (!Array.isArray(value.images) || value.images.some(function (x) { return typeof x !== "string" || !x.trim(); })))
    throw new Error("images must be an array of non-empty strings");
  if ((value.images || []).length + (value.image_url ? 1 : 0) > 5) throw new Error("at most 5 reference images");
  for (const key of ["seconds", "duration"]) {
    if (value[key] !== undefined && (!Number.isFinite(Number(value[key])) || Number(value[key]) <= 0 || Number(value[key]) > 3600))
      throw new Error(key + " must be between 1 and 3600");
  }
  // Preserve unknown extension fields and the original prompt, without a field whitelist.
  return Object.assign({}, value, { model: model });
}

function endpoint(ctx, suffix) {
  return String(ctx.baseUrl || "").replace(/\/+$/, "") + "/v1/videos" + suffix;
}

export function buildSubmitRequest(ctx) {
  if ((ctx.files || []).length) throw new Error("use JSON image_url or images, not file uploads");
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
  const statuses = { queued: "QUEUED", pending: "QUEUED", processing: "IN_PROGRESS", in_progress: "IN_PROGRESS", completed: "SUCCESS", failed: "FAILURE", cancelled: "FAILURE" };
  const result = { status: statuses[body.status] || "UNKNOWN" };
  if (result.status === "UNKNOWN") result.reason = "unrecognized status: " + String(body.status || "");
  if (body.progress > 0 && body.progress < 100) result.progress = body.progress + "%";
  if (result.status === "FAILURE") result.reason = body.error && body.error.message ? body.error.message : "task failed";
  return result;
}

export function extractUsage(ctx) {
  return { requests: 1 };
}

export function extractUsageOnComplete(task, result, body) {
  return { requests: 1 };
}

export function listArtifacts(task) {
  return task.status === "SUCCESS" ? [{ key: "video", type: "video" }] : [];
}

export function buildContentRequest(ctx) {
  if (ctx.artifactKey !== "video") throw new Error("artifact_not_found");
  return {
    url: endpoint(ctx, "/" + encodeURIComponent(ctx.upstreamTaskId) + "/content"),
    method: ctx.clientRequest.method,
    headers: { Authorization: "Bearer " + ctx.apiKey },
  };
}

export const protocols = {
  openai_video: {
    decodeRequest: function (ctx) {
      if (!ctx.body || ctx.body.kind !== "json") throw new Error("JSON body required; use image_url or images");
      const req = requestBody(ctx.body.value, ctx.model);
      return { kind: "submit", model: ctx.model, action: req.image_url || (req.images || []).length ? "image_to_video" : "text_to_video", requestBody: req };
    },
    render: function (ctx, task) {
      // New API manages the public task identity; preserve the vendor response.
      if (task.data && typeof task.data === "object" && !Array.isArray(task.data)) return task.data;
      const states = { NOT_START: "queued", SUBMITTED: "queued", QUEUED: "queued", IN_PROGRESS: "in_progress", SUCCESS: "completed", FAILURE: "failed" };
      const result = { id: task.task_id, object: "video", model: (task.properties || {}).origin_model_name || "", status: states[task.status] || "unknown", progress: Number(String(task.progress || "0").replace("%", "")), created_at: Number(task.created_at || 0) };
      if (task.status === "FAILURE") result.error = { code: "video_generation_failed", message: task.fail_reason || "The video generation task failed." };
      return result;
    },
  },
};
