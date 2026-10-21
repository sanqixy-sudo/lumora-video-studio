# oaireg omni 专用插件

版本 `1.1.0`，标识 `oaireg-omni`。适配本次检查的 New API `v1.0.0-rc.40`，插件 API v1。

`plugin.js` 是后台应导入的单个文件。`fixture.json`、`test.mjs` 用于离线验证，不需要导入。

## 解决的问题

显式声明 `omni-fast`、`omni-fast-no-water`，通过 `/v1/videos` 的插件协议解析保留原始 JSON 字段，绕过旧式 `TaskSubmitReq` 对 `aspect_ratio`、`image_url` 的过滤。单图、多图、横竖屏和扩展 JSON 字段均保留；提示词不修剪或改写。

插件使用通道保存的上游地址和密钥，源码没有真实密钥。支持提交、轮询、结果返回、视频内容读取。第一版只接受 JSON 和图片 URL，不支持 multipart 文件上传、Responses 协议或 remix。

没有声明共享的 OpenAI channelTypes，避免覆盖 Sora 和其他 OpenAI 通道。必须绑定专用的“任务插件”通道。

## 后台安装

2026-09-28 已由用户上传插件，并授权补齐专用通道，真实竖屏生成验收通过，详见 `DEPLOYMENT.md`。以下步骤供重装或其他环境使用。首次通过后台上传新插件通常会立即激活；请在停止新建 Omni 任务的短暂窗口内完成上传和通道绑定，避免中间出现模型已被插件接管但尚无匹配通道的情况。

1. 保存原 Oaire 通道配置，保留原通道处理历史任务；不要删除原通道。
2. 使用最高管理员进入 New API 的“任务插件”页面，选择上传，导入 `plugin.js`，也可以粘贴全部源码。
3. 核对名称“oaireg omni 专用插件”、标识 `oaireg-omni`、版本 `1.1.0`。若显示待激活，点击激活。
4. 新建独立通道，类型选择“任务插件”，绑定 `oaireg-omni`。上游地址、密钥、分组沿用原 Oaire 通道；地址使用站点根地址，例如现有 `https://newapi.oairegbox.cc`，不要追加 `/v1`。
5. 目前只开放原通道实际使用的 `omni-fast-no-water`；虽然插件也声明 `omni-fast`，有需求且令牌具备权限时再加入通道模型列表。模型映射留空，不映射到 `sora-2`。保留现有模型价格和分组倍率。
6. 用后台插件调试功能检查生成的请求体仍含 `aspect_ratio: "9:16"` 和 `image_url`，且模型未变化，再恢复用户提交。离线用例不能代替部署后的真实路由与上游成品验收；新的付费复测应单独授权。

NAS 保持原 New API 地址、密钥及 `POST /v1/videos` 调用方式。无需修改 New API 主程序或重新构建 Docker 镜像。

## 按次计费（1.1.0）

每个生成任务上报 `requests: 1`，提交和完成阶段保持一致；查询和轮询不会增加次数。客户端或上游的 seconds、duration、requests 不改变计费次数。页面字段为“生成次数”，单位为“次”。不再使用 1.0.0 的默认 4 秒及尺寸计费档位。

后台进入模型定价，选择可视化编辑器，填写“生成次数”的每次单价，加收费用填 0；费用试算的次数填 1。例如保持 3.45 USD/次，对应表达式：

```text
tier("request", u("requests") * 3.45)
```

手写表达式按 USD 解释，最终扣费仍受现有分组倍率影响。不要将任务计费表达式改写成普通 Token 计费的 `fixed()` 语法。

升级必须与价格公式配套进行：先把原来的固定金额公式改成不引用 seconds/size 的常数公式，等待配置缓存同步；上传并激活新版、等待插件热加载后，再换成引用 requests 的公式。保留旧版及价格备份。原本按秒或分辨率差价收费的模型，不能直接按本例迁移，需要先确定新的收费策略。

## 回退

先停止新的 Omni 提交。若新插件已有正在运行的任务，保留插件和绑定通道，等待任务结束及视频取回后再停用；立即停用会影响这些任务的查询或内容访问。

停用 `oaireg-omni` 并停用新建的专用通道，保留/恢复原 Oaire 通道。历史旧任务仍由原 Sora 路径处理。注意回退会恢复原先丢失画幅和参考图的故障，不代表问题已修复。

## 校验结果（2026-09-28）

- Node：36 个固定用例通过，加 4 个 decode → buildSubmitRequest 连续参数完整性检查，所有用例确认输入没有被修改。
- 当前服务器现有 New API 二进制：`plugin lint` 通过，`plugin test` 36/36 通过。
- 原生校验使用独立 CLI 进程和匿名内存文件，未导入数据库、未修改容器文件、未重启服务、未调用上游生成接口。

本地复跑：

```powershell
node integrations/new-api/oaireg-omni/test.mjs
```

在具有 New API 二进制和这两个文件的测试环境中复跑：

```sh
new-api plugin lint plugin.js
new-api plugin test plugin.js --fixture fixture.json
```

接口依据：[OAIRE 文档](https://docs.oairegbox.cc/#omni)；[本次部署 revision 的插件协议实现](https://github.com/QuantumNous/new-api/blob/0aec08fee811ec6136828fda790551b49e410301/plugins/tasks/sora/plugin.js)。
