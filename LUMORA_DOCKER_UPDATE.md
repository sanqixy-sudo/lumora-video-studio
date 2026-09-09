# 流光 Lumora 全站更新 · 20260908-lumora9-2

本次交付是 **Docker 源码更新 ZIP**，用于在原服务器构建镜像，不是 `docker load` 使用的预构建镜像。本机没有 Docker；用户已授权在原服务器构建、备份并更新。本文是安装与回退说明，部署实际结果另记于 runtime/deployment-v92/report.md。

## 更新内容

- 月报改为紧凑逐日矩阵，保留实际月份 28/29/30/31 天及上下月切换；排行限宽；修复日用量编辑弹层保存点击。

- v3 完成 Web Design Guidelines 全量修复及复查，新增表单离页保护、错误字段关联、复杂背景可读性和动态控件补齐。详见 `LUMORA_WEB_GUIDELINES.md`。

- 登录、用户端、管理后台、错误页统一采用已确认的 Lumora 设计，使用裁剪后的新标识。
- 双主题和跟随系统使用太阳、月亮、显示器图标；记住浏览器选择。
- 新建与短编辑抽屉、素材和作品组件、设置分组、轻动效、键盘焦点统一。
- 后台批次详情限定所属任务，按本地文件是否就绪显示下载入口；用户批次继续局部同步。
- Pod 渠道和 VEO 视频编辑保持下线，历史处理兼容代码及 Wuyin 能力保留。
- 没有新增数据库迁移，没有调整额度、角色权限、上游协议或已有页面地址。后台任务页仅增加可选 `batch_id` 筛选。

## 包内与保留项

`lumora-docker-update-20260908-v9.2.zip` 包含应用、原有迁移、依赖、Dockerfile、启动脚本、测试及验收说明。旁边的 `.sha256` 是 ZIP 校验文件，包内 `SOURCE_MANIFEST.json` 提供各文件摘要。

不包含 `.env`、服务器 Compose 文件、数据库、上传文件、生成视频、密钥目录、缓存及旧交付包。沿用原 Compose 服务名 `sora`、项目名、卷名、端口和目录挂载，避免误建空数据库。旧交付包保留用于回退。

## 在原目录更新

以下示例假设项目在 `/opt/sora`，服务名 `sora`，上传包在 `/tmp`。按实际部署路径执行，始终在原 Compose 项目内操作。

1. 更新前安排短维护窗口，备份当前配置与数据库，保留上传、输出和密钥目录。本次仍使用原容器启动逻辑。建议等正在处理的任务结束后再重建容器。
2. 校验更新包，给当前运行镜像打回退标签，备份源码和 Compose 文件。

```bash
cd /tmp
sha256sum -c lumora-docker-update-20260908-v9.2.zip.sha256
cd /opt/sora
docker image tag "$(docker compose images -q sora)" lumora-local:before-20260908-v9.2
cp docker-compose.yml ../sora-compose-before-20260908-v9.2.yml
tar -czf ../sora-source-before-20260908-v9.2.tar.gz app migrations scripts Dockerfile requirements.txt alembic.ini .dockerignore
# 单容器内置 PostgreSQL 的逻辑备份。外置数据库请沿用其原有备份方式。
docker compose exec -T sora bash -lc 'pg_dump -h /var/run/postgresql -U "${POSTGRES_USER:-sora}" "${POSTGRES_DB:-sora}"' > ../sora-db-before-20260908-v9.2.sql
test -s ../sora-db-before-20260908-v9.2.sql
unzip -o /tmp/lumora-docker-update-20260908-v9.2.zip -d /opt/sora
```

3. 在替换容器之前构建并检查新镜像；构建或测试失败时，原容器继续运行。

```bash
docker compose config --quiet
docker compose build sora
docker compose run --rm --no-deps --entrypoint /opt/venv/bin/python sora -B -m unittest discover -s tests
docker compose up -d --no-deps --force-recreate sora
docker compose ps
docker compose logs --tail 100 sora
curl -fsS http://127.0.0.1:8088/readyz
```

如果原 Compose 只配置 `image:` 而没有 `build:`，请按原部署方式构建并更新镜像标签；不要替换原挂载配置。实际端口以服务器现有配置为准。

4. 浏览器强制刷新，检查登录、双主题、生成设置、历史任务和下载、后台保存及权限。资源版本已统一为 `20260908-lumora9-2`。不需要通过付费生成来验证 UI。

不要执行 `docker compose down -v`、删除数据目录或更换 Compose 项目名。旧 CSS 文件即使因 ZIP 覆盖方式残留在服务器，也不会被新版模板加载。

## 回退

在原项目目录创建临时覆盖文件，仅切回旧镜像，保持服务、卷和挂载不变：

```yaml
# docker-compose.lumora-rollback.yml
services:
  sora:
    image: lumora-local:before-20260908-v9.2
```

```bash
cd /opt/sora
docker compose -f docker-compose.yml -f docker-compose.lumora-rollback.yml up -d --no-deps --no-build --force-recreate sora
curl -fsS http://127.0.0.1:8088/readyz
```

本次没有新增迁移，一般无需回退数据库。不要为界面回退覆盖更新后新增的任务数据。若服务器绑定挂载应用源码，还需从源码备份恢复对应文件，保持 `.env` 和数据目录原样。后续重新更新前，恢复正常 Compose 调用方式并妥善保存回退文件与镜像。

## 本地验收

工作区全站预览：`http://127.0.0.1:8100/design`。使用模拟数据和模拟提交，不连接业务数据库或付费上游。

详细结果见 `LUMORA_ACCEPTANCE.md`。截图及动效另包交付，位于工作区 `runtime/lumora_review`。源码包在新环境运行本地预览时需安装依赖，运行 `python scripts/preview_studio.py --serve`；可选运行 `node scripts/create_studio_preview_clip.cjs` 生成模拟视频。新环境没有旧版快照时，不提供旧版并列比较。

## v4 月报自适应修正

摘要和月报铺满内容区；用户与合计列固定，日期均分剩余空间。保留桌面最小 28px、手机/触控最小 44px 及大数字扩宽，仅表格内部滚动。侧栏收起及窗口变化自动适配，保留全站内容区最大宽度。

本轮重新执行 8 组月报深浅主题/屏宽检查（390、768、1440、1920px），覆盖可用宽度利用率、日期等宽、固定首列、侧栏收起、键盘导航、失败输入保留、六位数及 80 人 × 31 天压力场景；28/29/30/31 天月份切换、跨年和筛选保留全部通过，axe 检查无违规。更早的全站 534 状态等结果来自 v3 基线，本轮仅对受影响报表执行复查。视觉包更新月报截图，其余全站截图和动效沿用 v3 验收证据。

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
