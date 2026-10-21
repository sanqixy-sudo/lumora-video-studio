# 2026-09-28 部署与验收

用户先自行上传并启用插件，随后明确授权“由你配置并复测”。

## 已应用的配置

- 插件 `oaireg-omni`，名称“oaireg omni 专用插件”，版本 1.0.0。
- 服务端源码 SHA256 与本地一致：`8705f31508c020d6cf72cd08acc3208d10f22c9eebc45007b287a0e3e55796ef`。
- 新增通道 ID **24**，类型 **61（任务插件）**，绑定 `oaireg-omni`。
- 模型 `omni-fast-no-water`，分组 `Sora`，上游地址及凭证沿用通道 23；未修改模型价格和分组倍率。
- 原 23 号 Oaire 通道完整保留，可供旧任务查询。

后台浏览器自动化因本机 ACL 故障不可用，服务没有可用的根管理员 API token。已通过用户授权的 SSH 维护连接，在一个 SQLite 事务内新增 channels、对应 abilities 和明确标记 SSH 维护来源的 audit_logs 记录。原通道内容哈希前后相同；未伪造后台登录或修改账号凭证。服务自动刷新通道缓存，无需重启。

## 唯一一次真实复测

- NAS 新任务 **15660**，复制源任务 15649 的提示词、模型、参考图及 720x1280 设置。
- 用户 **肖杨**（ID 2），幂等 UUID `cb89da61-3d7a-54c1-bafb-a48c08ed2c83`。
- NAS 提交次数 1，POST HTTP 200，最终 completed，额度扣除 1 次，钱包剩余 397、预留 0。
- New API 任务 `task_bWM1ufpVW5PbEgjnp3TguUu1oJ3iDW7d`，通道 24，执行插件 `oaireg-omni@1.0.0`，generation 12。
- 上游任务 `task_Kz54MuHNNamnQOtiQHvNyXQUkg9aEiky`，最终 completed。
- 上游返回 `aspect_ratio=9:16`、`input_mode=reference-images`，没有错误。
- NAS 下载完成后 ffprobe 实测：**width=720，height=1280**。
- New API 记录的本次计费 quota=1725000，与此前旧通道成功任务 15658 的 quota 相同。

结果页：https://video.7cloudvps.com/app/jobs/15660/page

本次没有改 New API 主程序、NAS 请求代码或镜像，没有重启服务。历史横屏成品没有重新生成；仅新增上述一个验收任务。
