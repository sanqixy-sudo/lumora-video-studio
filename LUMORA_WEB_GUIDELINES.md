# Lumora Web Design Guidelines 全站复查

> v9 最新验收见 `LUMORA_PALETTE_CHECK.md`。下文原始全站及 v1–v8 数字为历史基线，末尾 v9 章节记录本轮复查。

版本：20260908-lumora9-2。检查日期：2026-09-08。

**结论：本地已验证范围通过；已确认缺陷全部修复并复查，无待修复的已确认问题。**

按用户指定的 `web-design-guidelines/SKILL.md` 执行。复查前重新下载官方规范：
https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md

本轮规范文件 SHA-256：`5a775e6411f790f518dbc9c1fa7c50a89e6873502d9a3534a6eb223a590bcfe8`。检查当前 31 个生产页面及其共享模板、脚本和样式，旧版并列快照仅用于回退对照。

## 检查—修复—复查记录

1. 初扫发现月份筛选缺少名称、空操作列表头、重复表格区域名称、错误页标题层级；代码核查补充图片尺寸、自动填充、主题色、动态控件与手机焦点问题。
2. 修复后扩展至编辑抽屉、账户菜单、任务操作菜单、媒体详情及手机导航，发现用户菜单移至页面根部后缺少区域语义，已修复。
3. 补测失败保存、重复失败、首个错误焦点、离页保护、100 条动态提示词和键盘预览；修复过早解除离页保护、隐藏分组错误焦点、按钮图标恢复、动态错误色等遗漏。
4. 实际背景像素补测发现浅色作品封面画幅文字仅 2.74:1，补充底衬后复测通过；同时修复跳转链接悬停可读性并扩大手机次级点击区。
5. 最终全量复查：458 个页面/展开状态 + 76 个空数据、筛选无结果、完成/失败及批次范围状态，**共 534 个视图，无自动违规、尺寸/自动填充缺失、页面横向溢出或页面脚本异常**。

## 已修复位置（按文件定位）

- `app/templates/admin/usage_monthly.html:13` — ✓ 月份筛选已补可访问名称。
- `app/templates/admin/dashboard.html:30` — ✓ 空操作列表头已改为“操作”。
- `app/templates/admin/queue.html:57` — ✓ 队列表格空表头已补齐。
- `app/templates/errors/403.html:1` — ✓ 错误页面使用一级标题和跳转主内容链接。
- `app/templates/workbench/login.html:11` — ✓ 登录控件自动填充、错误状态、跳转入口及移动焦点已统一。
- `app/templates/app/library.html:21` — ✓ 筛选区域补充有效分组角色。
- `app/templates/workbench/media_card.html:3` — ✓ 封面预览改为原生按钮；图片固定尺寸，视频关联提示词说明。
- `app/templates/admin/settings.html:12` — ✓ 数值与文本配置使用正确输入模式；保存仍包含全部分组。
- `app/static/theme.js:11` — ✓ 浏览器主题色随系统和手动主题同步。
- `app/static/ui.js:32` — ✓ 字段提示关联 aria-describedby；跨分组聚焦首个错误；重复失败清理旧关联。
- `app/static/ui.js:70` — ✓ 有效保存后才解除当前表单离页保护，失败保留输入并恢复按钮图标。
- `app/static/workbench/interactions.js:10` — ✓ 手机抽屉优先按钮焦点，避免自动打开输入键盘。
- `app/static/workbench/interactions.js:83` — ✓ 浮层操作区域具备语义和名称，仍保留门户布局、Esc 和焦点返回。
- `app/static/workbench/interactions.js:120` — ✓ 动态素材缩略图补尺寸。
- `app/static/workbench/micro-motion.js:41` — ✓ 侧栏位置测量先统一读取，再写动画，避免交错布局。
- `app/static/workbench/guidelines.js:5` — ✓ 各表格区域使用可区分的名称。
- `app/static/workbench/guidelines.js:14` — ✓ 超过 50 条的提示词与表格标记 content-visibility；原生输入无需逐键全量重建。
- `app/static/workbench/guidelines.js:24` — ✓ 真实编辑启用离页保护，保存/重置清除；不存草稿或密码。
- `app/static/workbench/guidelines.js:34` — ✓ 日期与统计展示采用 Intl；保留北京时间和服务端原协议。
- `app/static/workbench/guidelines.js:55` — ✓ 阅读折叠区状态进入 URL，可复制链接恢复。
- `app/static/workbench/guidelines.css:20` — ✓ 主内容焦点可见；滚动留出顶栏和提交栏空间；手机常用操作至少 44px。
- `app/static/workbench/collections.css:17` — ✓ 浅色封面画幅说明 2.74:1 的实测问题已修复，加深色底衬。
- `app/static/app.js:657` — ✓ 新增图片链接提供自动填充、拼写及示例提示。
- `app/static/app.js:755` — ✓ 动态提示词包含自动填充声明和可访问名称。
- `app/static/app.js:690` — ✓ 动态错误与额度提示采用主题错误色。

## 验证证据

| 检查 | 结果 |
|---|---|
| axe-core 4.10.3 | WCAG 2 A/AA、2.1 A/AA 和 best-practice；1440/390px × 深浅主题，534 个页面及状态通过 |
| 全站适配 | 31 页 × 375、390、768、1024、1440、1920px × 双主题，372 组通过；截图已更新 |
| 关键样板 | 60 组通过，包含登录/生成失败与素材、导入交互 |
| 质量与强化 | 29 + 33 组通过，涵盖横屏、CSS 200% 缩放、长字段、素材边界、轮询退避、文件就绪 |
| 常规交互 | 6 组后台/媒体回归通过；必要删除确认仍保留 |
| 规范专项 | 6 组通过：失败离页保护、跨分组错误关联、手机焦点、100 条延迟渲染与焦点无遮挡、URL 恢复、原生预览键盘操作 |
| 动效与媒体 | 七类动效中间帧/快速反向/焦点返回/减少动态效果通过；媒体最新响应优先、防重复与隐藏页释放通过 |
| 对比度 | 40 个公共令牌组合 ≥4.88:1；登录渐变、侧栏伪元素背景、媒体覆层 104 个文字区域像素补测，最低 4.99:1 |
| 单元测试 | 60 项通过；模拟上游，无付费生成 |

原始 JSON 位于 `runtime/guidelines_review/`、`runtime/lumora_review/` 和 `runtime/studio_review/`，随视觉验收 ZIP 交付。`axe.incomplete` 保留在原始报告中：渐变、SVG 和伪元素背景经上述像素补测；被抽屉/导航遮挡的非活动内容与可滚动表格不可见部分不按可见文字判定；短数字按实际主题颜色对验证。装饰字样位于 `aria-hidden`，无须满足正文对比度；关闭模态后跳转主内容入口恢复可用。

## 规范适配与保留边界

- 保留用户明确要求的轻收缩：原生 details 用 180–220ms 短时高度过渡，其余主要位移动画使用 transform/opacity；小范围控件颜色反馈保留 120ms。没有 transition: all、逐帧表格宽度动画或业务装饰循环；减少动态效果会关闭过渡。此项是已确认交互与通用“仅合成属性”建议的适配，不计为纯合成动画。
- 未保存提醒只保护当前页内编辑状态，不持久化草稿。临时素材选择/编辑抽屉不写入 URL；列表筛选、分页、页内分组和阅读折叠区可恢复。仅供本页处理的导入/选择控件保留稳定 ID，不向原请求加入无关字段。
- UI 主要时间用 Intl 呈现并固定 Asia/Shanghai；原始日志、ID、输入值、下载内容和 API 字符串保持原协议。界面语言沿用明确的 zh-CN，不通过 IP 推断语言。
- 系统字体和本地 SVG 无远端字体/CDN 首屏依赖；Jinja + 原生 JavaScript 没有 React hydration。无拖拽专用操作。静态首屏标识正常加载，列表媒体使用 lazy/preload=none。
- 视频具备可操作的播放控件/键盘预览和提示词说明。模拟片段无对白；真实生成视频音轨的字幕完整性需要结合实际内容验收，不能从模拟片段推定。

未执行真实触屏设备、Safari/Firefox、浏览器工具栏真实 200% 缩放、生产服务端到端和 Docker 镜像构建。本机无 Docker；当前结论是本地 Chromium 与模拟响应下的验证，不替代这些环境检查，也不宣称服务器提速。

## 重跑

先启动 `python scripts/preview_studio.py --serve`，使用本地模拟接口。Node 脚本通过 `SORA_PLAYWRIGHT` 指定已安装 Playwright 的模块路径；安装 Chromium。对比度 Python 脚本需 Pillow。

下载 axe-core 4.10.3 至 `runtime/axe.min.js`（仅测试依赖，不加载到生产页面）：
https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.3/axe.min.js

设置 `AUDIT_STATES=1` 后运行 `node scripts/audit_web_guidelines.cjs`；清除该变量、设置 `AUDIT_VARIANTS=1` 后运行状态补查。运行 `node scripts/check_lumora_guidelines.cjs`、`node scripts/check_lumora_contrast.cjs` 和 `python scripts/check_lumora_contrast.py` 完成专项复核。全站适配使用 `node scripts/check_lumora_full.cjs`。每轮规范复查前重新获取上面的官方规范文件。

## 交付

最新源码包 `release/lumora-docker-update-20260908-v9.2.zip`，配套 SHA-256 和 `SOURCE_MANIFEST.json`；视觉证据包 `release/lumora-visual-review-20260908-v9.2.zip`。更新/回退方法见 `LUMORA_DOCKER_UPDATE.md`。旧 v1、v2、v3 包保留；未部署服务器。

## 多用户月报补充修复与日历验收

用户指出通用表格拉伸导致列过宽。此前单用户、7 天预览未覆盖真实月报密度；通过可访问性或页面无溢出检查不能证明信息密度合理。本次新增专门的报表验收。

- `app/static/workbench/reports.css:5` — ✓ 月报按用户 × 每日次数的紧凑矩阵展示，桌面日期列均分剩余宽度且至少 28px，触控至少 44px；固定用户、月合计、日期表头与每日合计，大数字提高最小列宽，空间不足时仅表格内部横向滚动。
- `app/static/workbench/reports.js:1` — ✓ 依据实际日期列显示星期、周界线及可见日期范围；窄屏提供日期翻页，键盘方向键/Home/End 可定位每日数字。
- `app/templates/admin/usage_monthly.html:1` — ✓ 原有月份选择、上下月、筛选、导出及修改数量保留；按传入 days 循环，未写死 30 天。为逐日编辑提供包含用户/日期/次数的名称。
- `app/templates/admin/rankings.html:1` — ✓ 排行区域限宽，数字靠右，明确列宽；补充“查看每日用量”入口。
- `app/static/ui.js:131` — ✓ 将自定义模态移到背景树外，修复月报编辑弹层被背景 inert 连带禁用、保存按钮无法点击的问题。
- `scripts/preview_usage.py:1` — ✓ 改为 24 人完整月份的模拟数据，按真实日历生成；预览月份选择/上下月/筛选真实生效。修正旧排行样例 failed_count 与真实 failure_count 字段不一致造成的空值。

验证：8 组密集月报双主题/屏宽检查通过；720 个日用量按钮、固定首列/表头、失败保存保留、回到原日期、六位数列宽均通过。另用 80 人 × 31 天（2,480 格）及长账号名验证延迟渲染和容器滚动。月报弹层通过键盘/点击/错误恢复；复测共享媒体弹层和动效通过。并行扫描时一次弹层中间帧采样未捕获过渡，停止密集扫描后独立复测捕获到中间透明度并通过，未当作通过结果覆盖失败过程。

月份浏览器验收：2026-05 为 31 天、2026-04 为 30 天、2026-02 为 28 天、2024-02 为 29 天；每次切换的日期列、每日数据、月底编辑日期与导出参数一致。2026-12 → 2027-01 → 2026-12 跨年切换通过，保留 q/hide_zero。新增正式 `_month_nav` 闰年/非闰年及跨年边界回归，单元测试合计 60 项通过。生产月份聚合、北京时间、权限及扣额规则未改动。

证据：`runtime/guidelines_review/reports-matrix.json`、`calendar.json`、`usage-*.png`、`month-*.png`、`rankings-*.png`。重跑使用 `node scripts/check_lumora_reports.cjs` 和 `node scripts/check_lumora_calendar.cjs`。

## v4 月报自适应修正

摘要和月报铺满内容区；用户与合计列固定，日期均分剩余空间。保留桌面最小 28px、手机/触控最小 44px 及大数字扩宽，仅表格内部滚动。侧栏收起及窗口变化自动适配，保留全站内容区最大宽度。

本轮重新执行 8 组月报深浅主题/屏宽检查（390、768、1440、1920px），覆盖可用宽度利用率、日期等宽、固定首列、侧栏收起、键盘导航、失败输入保留、六位数及 80 人 × 31 天压力场景；28/29/30/31 天月份切换、跨年和筛选保留全部通过，axe 检查无违规。更早的全站 534 状态等结果来自 v3 基线，本轮仅对受影响报表执行复查。视觉包更新月报截图，其余全站截图和动效沿用 v3 验收证据。

- `app/static/workbench/reports.css:3` — ✓ 移除摘要的 1084px 宽度上限。
- `app/static/workbench/reports.css:5` — ✓ 报表由内容适宽改为容器全宽。
- `app/static/workbench/reports.css:9` — ✓ 表格以 100% 宽度均分日期列，使用最小宽度保障数字及触控，不再浪费右侧空间。
- `scripts/check_lumora_reports.cjs:7` — ✓ 增加宽度利用率、列等宽及侧栏适配断言，避免仅检查溢出遗漏大屏留白。

## v5 子管理员用量权限复查

修复 `app/templates/admin/usage_monthly.html:65`：每日合计的 title 仅对总管理员显示真实/展示次数；子管理员仅显示展示次数。子管理员无修改圆点、调整下划线、备注或编辑入口。JSON 不包含真实量和调整信息，XLSX 仅导出展示量，写入及恢复接口拒绝子管理员（403）。沿用隐藏用户过滤规则。

新增 `tests/test_usage_roles.py` 的 3 项测试通过，覆盖实际模板、JSON、XLSX 和 HTTP 写入权限；6 组子管理员浏览器检查通过（深浅主题 × 390/1440/1920px），月末列完整、表格横向滚动正常、无页面溢出及 axe 违规。本轮为角色专项复查，未重跑此前全部全站检查。v4 及更早交付包保留；该修复已包含在当前 v9 更新包。

浏览器复查先运行 `.venv/Scripts/python.exe -B -c "import sys;from pathlib import Path;sys.path.insert(0,'tests');from test_usage_roles import render_role;Path('runtime/usage-subadmin.html').write_text(render_role('sub_admin'),encoding='utf-8')"`，再在 8100 模拟预览服务运行时执行 `node scripts/check_usage_subadmin.cjs`。

## v6 手机端全站专项

新增统一触屏样式，修复用量弹层窄屏越界、部分链接/菜单/主题按钮点击区域及横屏表单字号。31 页双主题 × 6 种尺寸共 1,038 项页面/展开状态检查通过；7 组手机关键交互、63 项单元测试通过。旧 v5 及更早包保留。覆盖、复现、截图证据及真机未测范围见 `LUMORA_MOBILE_CHECK.md`。

## v7 图片链接读取确认

生成页每条图片链接可单独勾选“我确认图片可用，跳过读取检查”，仅跳过本机读取及未知尺寸检查；格式、数量、预设权限等原规则保留。网络错误按 HTTP/超时/连接/解析原因反馈。69 项单元测试、4 个专项双主题/手机桌面视图及 7 组既有手机交互通过。用户报告图片当前本机 HTTP 200、720×1280 PNG、完整性验证成功，旧服务器当时原因未知。详见 `LUMORA_IMAGE_LINKS.md`。旧 v6 及更早包保留，未部署。

## v8 提示词框精简

初始提示词框与动态新增框统一使用单句示例“例如：雨夜街道，镜头缓慢推进…”，删除多行占位提示和底部重复说明；移除提示词卡片外层聚焦描边，保留输入框及操作按钮的键盘聚焦提示。390/1440px × 深浅主题共 4 个局部浏览器检查通过，无页面横向溢出。证据见 `runtime/prompt_simplification/`。本轮仅调整提示词表现，未重跑此前全站测试；v7 和更早包保留，未部署。

## v9 雾蓝紫灰配色

全站主题、登录光影、侧栏、菜单、表单与浏览器主题色统一为雾蓝紫灰；Logo、布局及业务规则保持。新增长提示词列表聚焦滚动校正。31 页双主题、534 个规范状态、1,038 项手机矩阵、69 项单元测试及 6 组关键交互复查通过。当前颜色对比度、动效复测与未测范围，以 `LUMORA_PALETTE_CHECK.md` 为准。v8 原更新包及校验文件完整保留，本轮未部署服务器。

## v9.1 登录与退出补测

认证错误按实际原因显示，登录密码原样提交，退出使用原生 POST 与现有 303 导航。服务器当前 v7 的 chenlin 账号为 active，实际登录/退出正常，本次未复现现场故障，未部署或修改账号权限。新增认证与焦点专项通过，73 项单元测试通过。最终包为 v9.1，包含 v9 配色；v8 和 v9 保留。详见 `LUMORA_AUTH_CHECK.md`。

## v9.2 预设名称排序与服务器更新

素材选择抽屉按名称 A–Z 排序，忽略大小写，数字使用自然顺序。排序仅调整呈现，不改变预设 ID、权限和提交素材。实际浏览器已验证顺序、选择及应用正常，无脚本异常。v9.2 包含 v9 配色和 v9.1 认证修复，所有旧包保留。用户本轮已授权部署原服务器；早前章节的“未部署”仅描述各次历史交付。实际备份路径、镜像与部署验证结果见 runtime/deployment-v92/report.md。
