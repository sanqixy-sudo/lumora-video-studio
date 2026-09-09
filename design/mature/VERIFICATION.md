> glass-2 深化及登录入口修复见 [GLASS_2_REVIEW.md](./GLASS_2_REVIEW.md)。

> 最新 glass-1 样板验收见 [GLASS_REVIEW.md](./GLASS_REVIEW.md)。下文保留之前成熟平台样板的阶段记录。

# 五页样板验收记录

当前登录页已按后续反馈更新，登录项以 [封面墙验收](./LOGIN_WALL.md) 为准；以下保留初稿记录，其他四类样板仍适用。

日期：2026-09-08。环境：本地 Python/Jinja 模拟服务 8101、桌面 Chromium 自动化。所有提交均为模拟，无真实付费生成。

## 已执行

| 检查 | 结果与证据 |
|---|---|
| 五页 × 双主题 × 375、390、768、1024、1440、1920px 与 844×390 横屏 | 70 个组合无页面横向溢出；`evidence/matrix.json` |
| 五页 × 双主题 × 390 / 1440px 的 axe 检查 | 20 个页面状态无报告违规，运行时异常 0 |
| 注册、后台抽屉保存失败、素材抽屉、月报编辑弹窗 × 双主题 | 8 个打开状态无 axe 违规；`evidence/states.json` |
| 主要手机按钮的实测尺寸 | 登录、生成、后台用户主要操作均至少 44×44px；`evidence/additional.json` |
| 200% 等效布局 | 1440px / 2 = 720px CSS 视口，五页双主题共 10 个组合无横向溢出；这是等效回流检查，不冒充真实浏览器缩放 |
| 必要表单控件边界 | 28 个实测项，内外相邻背景对比度最低 3.33:1，均达到 3:1；`evidence/borders.json` |
| 核心交互 | 10 组通过；`evidence/interactions.json` |
| 轻动效 | 登录首次入场、侧栏、抽屉、菜单、最近任务、减少动态效果六组通过；`evidence/motion.json` 与 `motion-demo.webm` |
| 手机 100 条提示词焦点 | 最后一条下边缘 616px，提交栏上边缘 655px，未遮挡；`evidence/states.json` |
| 模拟视频播放 | readyState 4，720×1280，播放时间实际前进；`evidence/states.json` |
| 项目现有单元测试 | `python -B -m unittest discover -s tests`：78 项通过 |
| 当前生产静态文件 | 30 个文件与本轮改版前基线哈希一致，变更 0；`evidence/production-assets.json` |

10 组交互覆盖：提示词展开/失焦/收起、100 条导入和第 101 条拒绝、素材取消/应用和自然排序、登录失败保留、生成失败保留和重复点击、后台筛选和失败抽屉焦点返回、28/29/30/31 天及子管理员隐藏调整信息、长编号/模型换行和视频节点保留、手机导航/素材焦点返回、主题图标和系统跟随及刷新记忆。

## 修复与复查

- 浅色登录页英文品牌名继承透明度导致对比度仅 3.35 / 3.58：去掉透明度，采用公共次要文字色；同条件复查通过。
- 任务详情 h1 后直接进入 h3：将状态和参数改为 h2；同条件复查通过。
- 主题测试最初操作被图标替换后隐藏的 select，后改成点击实际图标；系统外观事件需要等待浏览器异步派发，补充状态等待后通过。未据测试时序误报修改主题业务逻辑。
- 空列表与筛选无结果使用不同文案；后台筛选使用模拟用户数据实际过滤。

## 检查边界

- 仅五类样板，不将旧的 31 页扫描结果计入本轮通过项。
- 未做真实手机、Safari/Firefox、软键盘、真实浏览器 200% 缩放和服务器环境验收。
- 没有声称服务器性能提升；此轮未改后端性能。
- 主题首屏脚本在样式前同步设置，手动/系统/刷新已操作验证；未做高速摄像级闪烁测量。
- 本轮样板复用原有权限、额度和接口逻辑；真实服务器角色、数据库迁移及运行中任务将在最终全站发布前回归。
- 登录三张图为原创静态插画；样板视频为模拟素材。

## 重跑

先启动 `scripts/preview_mature.py --serve`，再用项目现有 Playwright / Node 运行：

- `scripts/check_mature_samples.cjs`
- `scripts/check_mature_interactions.cjs`
- `scripts/check_mature_states.cjs`
- `scripts/check_mature_motion.cjs`
- `scripts/check_mature_borders.cjs`
- `scripts/capture_mature_comparison.cjs`

Node 默认使用已配置的本机 Playwright 路径，也可用 `SORA_PLAYWRIGHT` 指定安装路径。
