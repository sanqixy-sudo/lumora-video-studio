# Lumora v9 雾蓝紫灰配色验收

日期：2026-09-08。版本：20260908-lumora9。当前交付以本文记录为准；其他验收文档中的 v1–v8 章节是历史记录。

## 实施结果

全站使用低饱和蓝紫灰主题，保留布局、功能、Logo 原色与现有动效。用户端、管理后台、登录、表格、表单、菜单、弹窗、主题图标和浏览器主题色共用主题令牌。业务页保持平实底色，渐变仅用于已有登录品牌区域，SVG 图案几何结构不变。

| 用途 | 浅色 | 深色 |
|---|---|---|
| 页面 | #F1F3FA | #141827 |
| 内容面板 | #FAFBFF | #1C2335 |
| 内嵌区域 | #E9EDF6 | #171D2D |
| 弹窗 | #FDFDFF | #252E44 |
| 正文 | #20263A | #EAEFFA |
| 次要文字 | #59647C | #B1BCD1 |
| 主操作 / 悬停 | #4B57C8 / #3E48AC | #A9B9FF / #C3CDFF |
| 主按钮文字 | #FFFFFF | #19213E |
| 选中背景 | #E2E7FC | #2C3858 |
| 侧栏 | #E9EDF6 | #111625 |
| 控件边界 | #7886A3 | #7687A6 |

普通分隔线保持柔和，输入框、按钮等必要边界采用增强色。成功、警告、错误仍使用原语义颜色，已在新背景上复查。

补测发现长提示词列表的延迟渲染会使聚焦末项后滚动位置偏低，输入框被提交栏遮挡。修复为聚焦后下一帧校正可视位置，取消过期回调，不添加滚动动画、不改变提交参数。相同 100 条导入和手机反向 Tab 探针复查通过。

## 本轮实际执行

全部浏览器检查使用本地 8100 模拟预览和 Chromium，外部业务请求隔离，无真实付费生成。

| 检查 | 结果与证据 |
|---|---|
| 全站双主题及展开状态 | 458 项，零 axe 违规、自定义失败和页面脚本异常；runtime/guidelines_review/audit-final.json |
| 空数据、筛选无结果、失败/完成等状态 | 76 项通过；runtime/guidelines_review/audit-variants.json |
| 手机、平板及横屏 | 31 页 × 双主题，覆盖 320×740、375×812、390×844、430×932、768×1024、844×390，共 1,038 个页面/展开/页底检查通过；runtime/palette_review/mobile/report.json |
| 主题切换和刷新 | 8 项手动、系统跟随、偏好持久化和首次主题观察通过，theme-color 与 color-scheme 一致；runtime/palette_review/palette-check.json |
| 控件边界 | 28 处实际边界取样，最低 3.30:1；同上 |
| 主题文字 | 40 组配色，最低 4.82:1；runtime/studio_review/delivery-report.json |
| SVG、渐变、侧栏、视频背景文字 | 104 处实际背景取样，最低 5.12:1；runtime/guidelines_review/rendered-contrast.json |
| 关键交互 | 6 组通过：失败输入保留、错误聚焦、手机抽屉、100 条导入与焦点、最近任务状态恢复、空格控制预览；runtime/guidelines_review/behaviors.json |
| 动效 | 侧栏反向切换、菜单、最近任务、手机导航、媒体弹层、复制反馈及减少动态效果复测通过；runtime/lumora_review/motion-v2.json。首次弹层中间帧定时取样断言失败，重跑通过，属于时序敏感证据，不宣称所有设备的动画时序完全一致。 |
| 单元测试 | unittest discover -s tests，69 项通过 |

前后截图覆盖登录、生成、任务详情、月报及后台用户，390/1440px × 双主题。目录：runtime/palette_review/before 与 after；总览：runtime/palette_review/comparison.jpg。视觉交付包同时保留此前版本证据，其他目录应按各自验收文档区分历史结果。

## 交付与边界

- 预览：http://127.0.0.1:8100/design 与 /app?revision=mist9。
- 源码：release/lumora-docker-update-20260908-v9.zip；截图报告：release/lumora-visual-review-20260908-v9.zip；均附 SHA-256 文件和包内逐文件清单。
- 保留 v8 原包；安装和回退见 LUMORA_DOCKER_UPDATE.md。
- 未改变接口、权限、额度、数据库结构或生成流程；Pod 与 VEO 视频编辑保持下线。
- 本机没有 Docker，未构建容器镜像、未部署服务器。真实手机、Safari/Firefox、真实浏览器工具栏缩放及服务器环境未验收；本地视口模拟不能替代真机。不宣称真实服务器性能提升。

## v9.1 追加交付

最终应使用包含认证修复的 v9.1 更新包。提示词延迟渲染的一帧校正存在后续兄弟卡片重排，本次已追加编辑时解析完整卡片高度，并通过 80 帧稳定性检查。详细新测试和服务器观察见 `LUMORA_AUTH_CHECK.md`；本文上述颜色矩阵证据仍适用，v9 原包保留但不作为推荐安装包。
