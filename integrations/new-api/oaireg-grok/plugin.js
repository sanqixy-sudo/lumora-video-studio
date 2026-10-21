// New API task-plugin API v1. Prices belong to administrator configuration.
const MODELS = ["grok-imagine-video", "grok-imagine-video-1.5-preview", "grok-imagine-video-6s"];
const SECONDS = { type: "number", unit: "second", description: { en: "Video duration", zh: "视频时长" } };
const REQUESTS = { type: "number", unit: "count", description: { en: "Generations", zh: "生成次数" }, unitLabel: { en: "request", zh: "次" } };
function resolutionSchema(values) {
  return { enum: values, description: { en: "Resolution", zh: "分辨率" } };
}
const STANDARD_SCHEMA = { seconds: SECONDS, resolution: resolutionSchema(["480p", "720p"]) };
const PREVIEW_SCHEMA = { seconds: SECONDS, resolution: resolutionSchema(["480p", "720p", "1080p"]) };
export const meta = {
  apiVersion: 1, key: "oaireg-grok", name: "oaireg grok 专用插件", version: "1.0.0",
  author: { name: "Lumora" },
  description: { en: "OAIRE Grok video with per-resolution duration billing and a fixed-count 6s model.", zh: "保留 Grok 画幅及参考图；1.0 / 1.5 按分辨率和秒数计费，6s 定档按次计费。" },
  models: MODELS, fetchMode: "per_task", upstreams: ["vendor"], protocols: ["openai_video"],
  usageSchema: { seconds: SECONDS, resolution: PREVIEW_SCHEMA.resolution, requests: REQUESTS },
  usageProfiles: [
    { models: [MODELS[0]], schema: STANDARD_SCHEMA, examples: [
      { label: "480p · 6 秒", facts: { seconds: 6, resolution: "480p" } },
      { label: "720p · 6 秒", facts: { seconds: 6, resolution: "720p" } },
    ] },
    { models: [MODELS[1]], schema: PREVIEW_SCHEMA, examples: [
      { label: "480p · 6 秒", facts: { seconds: 6, resolution: "480p" } },
      { label: "720p · 6 秒", facts: { seconds: 6, resolution: "720p" } },
      { label: "1080p · 6 秒", facts: { seconds: 6, resolution: "1080p" } },
    ] },
    { models: [MODELS[2]], schema: { requests: REQUESTS }, examples: [
      { label: "固定 6 秒 / 480p · 1 次", facts: { requests: 1 } },
    ] },
  ],
};

function ratioFromSize(size) {
  const aliases = { portrait: "9:16", landscape: "16:9", square: "1:1", "9:16": "9:16", "16:9": "16:9", "1:1": "1:1" };
  if (aliases[size]) return aliases[size];
  if (typeof size !== "string" || !/^[1-9][0-9]*x[1-9][0-9]*$/.test(size)) throw new Error("size must be WxH, portrait, landscape or square");
  const dimensions = size.split("x").map(Number);
  const ratio = dimensions[0] / dimensions[1];
  // Normalize the vendor's legacy pixel selector to the nearest supported ratio.
  return ["9:16", "1:1", "16:9"].reduce(function (best, value) {
    const parts = value.split(":").map(Number), previous = best.split(":").map(Number);
    return Math.abs(ratio - parts[0] / parts[1]) < Math.abs(ratio - previous[0] / previous[1]) ? value : best;
  }, "9:16");
}

function normalize(value, model) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("JSON object required");
  if (!MODELS.includes(model)) throw new Error("unsupported OAIRE Grok model");
  if (typeof value.prompt !== "string" || !value.prompt.trim()) throw new Error("prompt is required");
  const req = Object.assign({}, value, { model: model });
  const fixed = model === MODELS[2];
  const allowed = model === MODELS[1] ? ["480p", "720p", "1080p"] : ["480p", "720p"];
  const seconds = value.seconds === undefined ? 6 : value.seconds;
  if (!fixed && !((typeof seconds === "number" && Number.isInteger(seconds)) || (typeof seconds === "string" && /^[0-9]+$/.test(seconds))))
    throw new Error("seconds must be an integer from 1 to 15");
  if (!fixed && (Number(seconds) < 1 || Number(seconds) > 15)) throw new Error("seconds must be from 1 to 15");
  req.seconds = fixed ? "6" : String(Number(seconds));
  req.resolution = fixed ? "480p" : (value.resolution === undefined ? "480p" : value.resolution);
  if (!fixed && !allowed.includes(req.resolution)) throw new Error("unsupported resolution for this model");
  if (value.aspect_ratio !== undefined && !["16:9", "9:16", "1:1"].includes(value.aspect_ratio))
    throw new Error("aspect_ratio must be 16:9, 9:16 or 1:1");
  const sizeRatio = value.size === undefined ? null : ratioFromSize(value.size);
  if (sizeRatio && value.aspect_ratio && sizeRatio !== value.aspect_ratio) throw new Error("size conflicts with aspect_ratio");
  const ratio = value.aspect_ratio || sizeRatio || (fixed ? "9:16" : "16:9");
  req.aspect_ratio = ratio;
  // Pixel size is a ratio selector, never a resolution or billing selector.
  if (fixed) req.size = { "9:16": "720x1280", "16:9": "1280x720", "1:1": "960x960" }[ratio];
  else delete req.size;

  const aliases = ["image", "image_url", "image_reference", "images", "image_urls", "reference_images", "input_reference"];
  const present = aliases.filter(function (key) { return value[key] !== undefined; });
  if (present.length > 1) throw new Error("use only one reference image field");
  let images = [];
  if (present.length) {
    const key = present[0], input = value[key];
    const arrayField = ["images", "image_urls", "reference_images"].includes(key);
    if (arrayField && !Array.isArray(input)) throw new Error("reference images must be an array");
    images = arrayField ? input : [input];
    if (!images.length || images.some(function (image) { return typeof image !== "string" || !image.trim(); }))
      throw new Error("reference images must be non-empty strings");
    if (images.length > 7) throw new Error("at most 7 reference images");
    if (model === MODELS[0] && images.length > 1) throw new Error("Grok 1.0 supports a single reference image");
    if (!fixed && req.resolution === "1080p" && images.length > 1) throw new Error("1080p supports a single reference image");
  }
  aliases.forEach(function (key) { delete req[key]; });
  if (images.length === 1) req[fixed ? "image_url" : "image"] = images[0];
  else if (images.length) req.reference_images = images.slice();
  return req;
}

function mode(req) { return req.image || req.image_url || (req.reference_images || []).length ? "image_to_video" : "text_to_video"; }
function endpoint(ctx, suffix) { return String(ctx.baseUrl || "").replace(/\/+$/, "") + "/v1/videos" + suffix; }
function outputURL(body) {
  if (!body || body.status !== "completed") return "";
  const first = Array.isArray(body.data) ? body.data[0] : null;
  for (const url of [body.video_url, first && first.url, body.metadata && body.metadata.url]) {
    if (typeof url === "string" && /^https?:\/\/[^\s]+$/.test(url)) return url;
  }
  return "";
}
export function buildSubmitRequest(ctx) {
  if ((ctx.files || []).length) throw new Error("use JSON reference image URLs or data URIs, not file uploads");
  return { url: endpoint(ctx, ""), method: "POST", headers: { Authorization: "Bearer " + ctx.apiKey, "Content-Type": "application/json" }, body: normalize(ctx.requestBody, ctx.upstreamModel || ctx.model) };
}
export function extractUsage(ctx) {
  const req = normalize(ctx.requestBody, ctx.upstreamModel || ctx.model);
  return req.model === MODELS[2] ? { requests: 1 } : { seconds: Number(req.seconds), resolution: req.resolution };
}
export function extractUsageOnComplete() {
  // New API retains submission facts; untrusted response fields cannot change the bill.
  return {};
}
export function parseSubmitResponse(ctx, resp) {
  const body = resp.body || {}, id = body.id || body.task_id;
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
  if (["QUEUED", "IN_PROGRESS"].includes(result.status) && Number.isFinite(Number(body.progress)) && Number(body.progress) > 0) result.progress = Math.min(99, Number(body.progress)) + "%";
  if (result.status === "FAILURE") result.reason = typeof body.error === "string" ? body.error : body.error && body.error.message ? body.error.message : "task failed";
  if (result.status === "SUCCESS") {
    const url = outputURL(body);
    if (!url) return { status: "UNKNOWN", reason: "completed response is missing a video URL" };
    result.progress = "100%"; result.url = url; result.remoteUrl = url;
  }
  return result;
}
export function listArtifacts(task) { return task.status === "SUCCESS" && outputURL(task.data) ? [{ key: "video", type: "video" }] : []; }
export function buildContentRequest(ctx) {
  if (ctx.artifactKey !== "video" || ctx.status !== "SUCCESS") throw new Error("artifact_not_found");
  const url = outputURL(ctx.data), method = (ctx.clientRequest || {}).method || "GET";
  if (!url) throw new Error("video URL is unavailable");
  if (!["GET", "HEAD"].includes(method)) throw new Error("content only supports GET or HEAD");
  return { url: url, method: method, credentialless: true };
}
export const protocols = {
  openai_video: {
    decodeRequest: function (ctx) {
      if (!ctx.body || ctx.body.kind !== "json") throw new Error("JSON body required; use reference image URLs or data URIs");
      const req = normalize(ctx.body.value, ctx.model);
      return { kind: "submit", model: ctx.model, action: mode(req), requestBody: req };
    },
    render: function (ctx, task) {
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
