# oaireg flow omni 专用插件

版本 `1.1.0`，标识 `oaireg-flow-omni`，模型 `flow-omni-1.1-flash`。适配已检查的 New API `v1.0.0-rc.40`，插件 API v1。

后台只需要导入本目录的 `plugin.js`。`fixture.json` 和 `test.mjs` 用于离线测试。1.1.0 更新增加按次用量字段；本次更新没有进行付费生成测试。

## 功能

独立处理 Flow Omni 的 JSON 请求，保留 `aspect_ratio`、`size`、`resolution`、参考素材及扩展字段，避免旧通用视频解析路径过滤参数。提交和查询使用通道配置的上游根地址、密钥和 `/v1/videos` 接口，源码不包含真实密钥。

| 模式 | 请求字段 |
| --- | --- |
| 文生视频 | `prompt` |
| 图生视频 | `prompt` 加 `images` 数组或 `image` 字符串 |
| 视频编辑 | `prompt` 加 `input_reference` 字符串，可同时带图片 |

存在 `input_reference` 时按视频编辑处理。图片和视频支持上游接受的 URL 或 Base64；不支持 multipart 上传。Flow 使用 `image` / `images`，传入另一个 Omni 接口的 `image_url` 会明确报错，避免参考图被悄悄忽略。

画幅支持 `9:16`、`16:9`；未指定时使用上游默认值。`size` 和 `aspect_ratio` 同时存在时原样保留，由上游按 `size` 优先处理。输出固定 720p、约 8 秒，不自动插入或修改时长。

官方建议参考图不超过 6 张，插件没有将建议误设为硬限制。参考视频最多 1 个、不超过 15 秒，Base64 解码后不超过 64 MB；素材格式、大小、时长和可访问性仍由上游校验，插件不会预先下载素材。

只有上游明确返回 `completed` 且提供有效视频 URL 才认定完成；运行中即使进度为 100 也不提前标记成功。视频读取使用完成响应的 `video_url`（兼容 `data[0].url`、`metadata.url`），下载请求不携带通道密钥。

## 在 New API 中导入

首次上传插件通常立即激活，并接管其声明模型的解析。请在暂时停止提交 Flow 新任务的窗口内完成插件上传和通道绑定。

1. 最高管理员进入“任务插件”，上传 `plugin.js`，核对名称“oaireg flow omni 专用插件”、标识 `oaireg-flow-omni`。若待激活，点击激活。
2. 新建独立通道，类型选择“任务插件”，绑定 **`oaireg-flow-omni`**。不要绑定原来的 `oaireg-omni`，也不要修改现有 24 号 Omni 通道。
3. 填写具备 Flow 权限的上游根地址及密钥。地址不要追加 `/v1`；插件会补齐接口路径。现有 Omni 密钥是否能访问 Flow，需要按实际账户权限确认。
4. 模型选择 `flow-omni-1.1-flash`，不映射成 `omni-fast`、`omni-fast-no-water` 或 Sora。New API 本地分组按使用者的令牌权限配置；官方文档中的上游分组当前称为 `Gemini flow`，不要求本地分组同名。
5. 配置模型按次价格及分组倍率，核对下述计费说明。后台调试请求应保留竖屏参数和参考素材字段。
6. 恢复提交前，另行进行一次经过授权的真实链路测试，核对任务路由、实际视频宽高、下载与扣费。离线校验不能替代这一项。

不需要修改 New API 主程序或重建镜像。插件没有声明共享 OpenAI 通道类型，只适用于绑定它的独立“任务插件”通道。

## 计费

Flow 按次计费。插件提供固定数值 `requests: 1`（生成次数，单位“次”）和字符串用量事实 `mode`：`text-to-video`、`image-to-video`、`video-to-video`，不使用视频秒数倍率。完成时也固定上报 1 次，保留提交阶段的生成方式。

官方文档对视频编辑和文生/图生标注了不同价格。管理员应根据账户实际成本，配置按次价格或使用 `mode` 区分定价；插件不会自动写入任何价格，也不沿用旧 Omni 的历史时长计费事实。上线前必须核对实际账单，不能仅凭离线用例判定扣费一致。

后台可视化定价会按“文生视频 / 图生视频 / 视频编辑”列出行，填写各行“生成次数”的每次单价，加收费用填 0，试算次数填 1。不要把次数单价填成秒单价。没有配置价格的模型保持未定价，不自动套用 Omni 售价。

模型广场的单位展示依据 `requests` 的 `count` 元数据和“次”标签；公式需引用 `u("requests")`，单纯的常数表达式可能仍显示为特殊表达式。手写公式使用 USD。

## 与流光项目的边界

当前流光项目已有 Flow 文生/图生请求构建逻辑，使用 `images` 和 `aspect_ratio`。本次只新增 New API 插件，未改动 NAS 应用、模型列表或页面。

插件支持视频编辑 API，但流光当前创建页面和后端尚未开放参考视频提交；要在流光网页使用视频编辑，需要另行补齐这部分功能。

## 回退

先停止新建 Flow 任务。插件通道已有任务时，保留插件和通道，等任务完成、成品取回后再停用，以免影响查询和下载。之后停用本插件及其独立通道；原 Omni 插件不受影响。恢复旧 Flow 通道不代表原通用解析路径已能完整保留参数。

## 验证结果（2026-09-28）

- Node：72 个固定用例、10 个 decode → submit 连续参数完整性检查通过，并检查输入未被修改。
- 服务器当前 New API 二进制：`plugin lint` 通过，`plugin test` **72/72** 通过。
- 原生校验使用独立 CLI 进程和匿名内存文件，未安装插件、未修改通道或数据库、未重启服务、未调用生成接口。

本地复跑：

```powershell
node integrations/new-api/oaireg-flow-omni/test.mjs
```

在具有 New API 二进制的测试环境中复跑：

```sh
new-api plugin lint plugin.js
new-api plugin test plugin.js --fixture fixture.json
```

接口依据：[OAIRE Flow Omni 文档](https://docs.oairegbox.cc/#flow-omni)。原生验证基于服务器部署 revision `0aec08fee811ec6136828fda790551b49e410301`。
