# NAS 生成页多规格模型接入规划

日期：2026-09-29。状态：已进入实施，进度与验证记录见同目录 notes 文件。本文件为实施依据。

## 目标与界面

保留现有生成页四列（模型、APP 名称、地区、批次名称）。将模型下方的画幅按钮与固定规格文字换成一行紧凑控件：

`清晰度 [720p ▾]   画幅比例 [竖屏 9:16 ▾]   时长 [10 秒 ▾]`

- 每个控件约 120–150px，复用已有自定义下拉与动画、键盘交互；小屏自动换行，不横向溢出。
- 模型名称不再绑定秒数。所有模型统一使用三个同样外观的下拉框，固定规格也使用单选项下拉，不另做静态标签或特殊布局。
- 用户补充要求：原有约 10 秒的 Omni，界面统一显示「清晰度 720p」「画幅比例 9:16 / 16:9」「时长 10 秒」。清晰度和时长各只有一个选项，比例仍可切换；10 秒是页面固定规格，不承诺上游实际成片恰好 10 秒。其他适配器按自身真实固定时长，例如 Flow 保持原有 8 秒，不能为了统一界面而改调用。
- Omni 调用契约保持不变：新增选择器仅统一展示与表单状态，适配器仍生成原来的请求字段。原来不发送 resolution/seconds 的 Omni，不因为 UI 有字段就补发；原来发送的字段和值也保持原样。
- 切换模型保留仍然有效的参数；不支持的值回到模型默认值，并显示简短提示。不清空提示词、APP、地区和素材。
- 管理员默认模型继续有效；老的 `key:id:seconds` 默认配置和客户端草稿兼容转换。
- 参数在整个批次共用；任务详情同时区分请求规格与成片实际尺寸/时长。

## 模型能力

根据 [OAIREGBOX Grok 文档](https://docs.oairegbox.cc/#grok)，本次仅接入两个可变时长模型，不开放独立的 `grok-imagine-video-6s` 模型；正常模型仍允许选择 6 秒。

| 模型 | 清晰度 | 比例 | 时长 | 图片限制 |
| --- | --- | --- | --- | --- |
| grok-imagine-video | 480p、720p | 9:16、16:9、1:1 | 整数 1–15 秒 | 最多 1 张 |
| grok-imagine-video-1.5-preview | 480p、720p、1080p | 9:16、16:9、1:1 | 整数 1–15 秒 | 480p/720p 最多 7 张；1080p 最多 1 张 |
| 现有 Omni / Flow 等 | 保留各自支持范围 | 保留各自支持范围 | 固定规格按现有协议 | 保留既有规则 |

界面无历史选择时 Grok 默认 480p、6 秒，比例沿用页面竖屏 9:16；三项均显式发送，不依赖上游默认横屏。上游清晰度档位不能被当成精确成片像素保证。

## 已确认的代码约束

- `app/services/model_choices.py` 当前按秒数枚举模型，值为 `key:{id}:{seconds}`；`app/api/user/routes.py::_parse_model_choice` 同样从选项读取秒数。
- `app/services/provider_keys.py` 的 `PROVIDER_SECONDS` 和 `model_id_for_seconds` 依赖固定秒数字段。通道表已有通用 `model_id`，Grok 应使用它，不能继续添加每秒一个数据库字段。
- `reference_images.py::dimensions_match_size_ratio` 与 `app.js::ratioMatches` 实际要求像素完全相同，并非仅检查宽高比。新的比例策略需要独立实现，不能破坏仍需要精确尺寸的旧适配器。
- Job 当前只有 `model/seconds/size`；请求在 `sora_api.py` 构造，worker 在独立提交/轮询/下载流程工作。
- `job_regeneration.py` 校验仍依赖秒数模型映射；重试复制了 `seconds/size/model`，需要同步复制新增参数。
- 通道删除已有保留历史的实现：被 Job 引用时标记 `deleted`，未引用才物理删除。

## 实施顺序

### 1. 打通一个 Grok 文生视频的完整路径

- 增加 `app/services/model_capabilities.py`：按 provider/model 定义清晰度、比例、时长枚举或范围、默认值、按清晰度变化的素材上限和图片策略。后端校验与前端选项使用同一份能力描述。
- 新 provider 使用 `oaire_grok`，避免 `grok` 旧别名被归一化到已退役的 `podgrok`。
- 每个 Grok 模型使用一个 NAS 通道配置，复用现有 ProviderKey `model_id`、地址、密钥、并发配置；后台显示模型选择，不要求填写 4/5/8/10/12/15 秒模型 ID。
- 新增 `app/services/oaire_grok.py`，扩展 `sora_api.py`、worker 参数传递和响应处理：NAS → 现有 New API → Grok 专用插件 → 上游。NAS 使用现有 New API 入口和授权令牌，不意外直连绕过插件。
- POST JSON 明确包含 `model/prompt/resolution/aspect_ratio/seconds`；seconds 使用协议要求的字符串。GET 查询与下载沿用现有异步管线，日志记录去除凭据后的请求参数以便核对。
- `Job` 增加可空的 `resolution/aspect_ratio`，`seconds` 继续保存所选时长；创建新 Alembic 迁移，旧数据通过旧 size 兼容读取，不改历史请求含义。Grok 的请求以新字段为准，不通过假定的像素 size 推导收费清晰度。
- 修改所有创建入口（单条、批量、异步与表单）和 schema/service，使非法组合在建任务、冻结额度、提交上游之前被拒绝。后端根据已授权的通道及模型校验客户端数据。

### 2. 接通紧凑选择器与素材校验

- 修改 `app/templates/workbench/dashboard.html`、`app/static/app.js`、`app/static/mature/creation.css`；复用 `app/static/workbench/form-controls.js/css`，处理动态 options 更新、焦点、Esc、键盘选择和减少动画偏好。
- 更新 `model_choices.py`、管理员默认模型设置、`creation-history.js`/草稿中实际保存模型规格的相关代码。新的模型标识与时长分离，老标识只作兼容解析，不让旧秒数覆盖新的选择。
- 预设与图片链接统一显示真实宽高、比例和检测状态；加载失败有重试入口，过期异步检测结果不能覆盖新图片或新比例的结果。
- Grok 按宽高比计算，建议相对偏差 1% 内视为匹配（例如 1080×1920 和 720×1280 都符合 9:16）。不是要求图片像素等于目标视频像素。
- 比例不一致属于本地提醒策略：提供切换到支持的图片比例、换图或明确确认继续；不自动修改图片。该策略不是上游已证实的硬限制，实施时文案不得误导。确认应绑定图片集合及当前目标比例，变化后重新检测，后端复核。
- 1.5 多图逐张标注检测结果；从多图切到 1080p 时提示最多一张并阻止提交，保留已选素材供用户调整，不静默丢弃图片。单图传 `image`，多图传 `reference_images`。
- 同一协议后续新增清晰度/秒数通过能力描述扩展；完全不同的上游协议仍需要适配器，不承诺任意模型零代码接入。

### 3. 兼容重试、历史与退役渠道

- `job_regeneration.py` 改用能力校验，失败重试保留原批次，复制模型、清晰度、比例、秒数和素材，不读取当前页面默认值。
- 详情、列表和下载后媒体元数据展示正确；保留原有批次 ZIP 命名及多包依次下载流程。
- 将 `sora_api`、`seedance` 纳入退役策略，移除新建/编辑渠道的可选入口与生成页选项；旧表单直提也拒绝。
- 部署前只读检查 NAS 这两类通道的 queued/submitting/processing/download_waiting 等在途任务和历史引用。先停止新提交，保留完成在途任务所需的凭据及查询路径，排空后调用既有删除逻辑；不连带删除任务、批次或文件。
- 默认模型若引用被移除通道，清空失效默认并提示管理员设置新默认，不擅自选择更贵模型。
- New API 的 Grok 分辨率计费配置保持现状；NAS 当前按生成次数的额度体系保持现状。本次不把美元费用变成 NAS 积分或按秒扣用户额度。

## 验证与上线

新增 `tests/test_grok_integration.py`、`tests/test_model_capabilities.py`，覆盖：

1. 两模型、各清晰度、三个比例与 1/6/15 秒正确编码；0/16 秒、标准版 1080p、非法比例、伪造模型拒绝且不扣额度、不提交上游。
2. 单图/多图字段、7/8 张边界、1080p 多图拒绝；同宽高比不同像素通过、比例不一致提示、换图后旧确认失效。
3. 模拟从提交、排队、完成、下载到媒体元数据的完整过程；失败重试仍在原批次，规格不漂移；重复点击不重复建任务。
4. 既有 Omni / Flow 请求字段和图片策略不变，固定时长不能被篡改；针对原 Omni 文生、单图、多图及横竖两种比例，以修改前实际 payload 为基准做等值回归，确保 UI 新增清晰度和时长选择器不增加/遗漏任何上游字段。页面三项外观统一，原 Omni 固定为 720p/10 秒且比例可选。Sora/Seedance 不可新建但历史查看下载正常。

回归命令（实施后执行，不代表规划阶段已经通过）：

```powershell
$env:PYTHONPATH='tests'
.venv/Scripts/python.exe -m unittest test_grok_integration test_creation_features test_omni_image_aspect test_image_confirmation test_oaire_omni_integration test_flow_omni_integration test_batch_regeneration test_provider_retirement test_template_compilation test_worker_download_isolation -q
```

浏览器验证：宽屏一行紧凑显示、窄屏换行；下拉无裁切、切换规格同步、暗色与键盘可用；参考图选取/外链/失败重试完整走通。

发布顺序：备份数据库与相关配置 → 加兼容字段 → 部署支持新旧字段的代码 → 配置两个 Grok 通道并检查令牌可见模型 → 检查真实出站 JSON → 按用户授权范围安排最少量生产生成验收并核对实际成片与计费 → 排空后移除旧渠道。规划阶段不执行付费生成、部署或生产删除。

请求代理、下载代理、下载并发和两分钟下载重试间隔保持现有配置。上线前后核对在途任务数量与 worker 状态。

## 恢复与待实测事项

- 失败时暂停新增 Grok 入口、回滚应用版本，保留新增可空字段；若已有 Grok 在途任务，保留能处理它们的 worker，不能直接回退成无法识别该 provider 的版本。
- 旧渠道移除前备份非公开配置；恢复通过原通道记录与状态，禁止通过删除历史任务规避引用。
- 本计划已查本地源码与公开协议；尚未核验 NAS 当前通道库存、在线令牌模型权限、真实 Grok 图片与最终画幅行为。实施时先核验这些事实。
- 图片不匹配采用“提醒并允许明确继续”是本计划的推荐交互；若用户希望严格阻止，可只调整该策略。
- 实施记录写入 `docs/plans/grok-creation-capabilities.notes.md`，记下偏离本计划的具体原因与最终验收结果。
