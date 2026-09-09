# Sora 全站改版 · 2026-09-07

本版本重做生成页，统一登录、用户端及管理后台的深浅主题。任务页仍显示全部任务，批次详情单独展示所属任务。没有数据库结构迁移，没有修改正常渠道的上游请求协议、额度扣退逻辑或用户权限。

## 主要变化

- 顶部生成设置、独立素材与提示词面板、常驻提交栏；模型按渠道分组，素材预设支持缩略图。
- 提示词只计算非空项。导入默认追加，替换需确认；超出 100 条明确报错。保存失败保留页面输入，不新增持久化草稿。
- 默认跟随系统主题，可手动切换。登录背景微动效尊重减少动态效果设置；手机可展开导航。
- 用户、密钥新增表单可展开，设置分组显示说明；用户端和后台共用按钮、表格、错误提示和确认弹窗。
- 批次详情局部刷新并在后台暂停，网络失败退避；按本地文件是否存在决定下载入口，不将上游完成等同于本地就绪。
- 移除下载失败页跨范围的全量删除入口，任务管理页仍保留原清理能力。
- PodSora、PodGrok 不再接受新任务、新增配置、修改配置和启用操作；旧密钥只读展示，已有任务继续处理、查询、下载。
- VEO Omni 新任务仅支持多图生成；视频编辑仅保留历史适配。Wuyin 的 1 图 / 1 视频能力保持不变。

## 本地预览和验证

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -B scripts/preview_ui.py --serve
```

打开 `http://127.0.0.1:8099/`。预览使用虚构账号、模拟任务及 SVG 图片，仅监听本机，所有 POST 操作返回 405，不会生成视频或连接业务数据库。生成页 `/app`，登录页 `/login`，后台 `/admin`。关闭预览进程即可停止服务。

浏览器回归脚本为 `scripts/check_ui.cjs`，需要 Node.js 与 Playwright Chromium；可通过 `SORA_PLAYWRIGHT` 指定 Playwright 包的绝对路径。它会模拟接口错误、检查渠道切换和导入交互，在 `runtime/ui_review` 保存截图与报告。正式服务不依赖 Playwright。

## Docker 更新

源码更新包在 `release/sora-console-redesign-20260907.zip`，旁边提供 SHA-256 校验文件。包不包含 `.env`、Compose 配置、数据库、密钥文件、生成视频或本地运行数据。

以下假设项目目录 `/opt/sora`，Compose 服务名 `sora`。保留服务器现有 `.env`、`docker-compose.yml`、`data` 目录和 PostgreSQL 数据卷。

```bash
cd /tmp
sha256sum -c sora-console-redesign-20260907.zip.sha256

cd /opt/sora
# 备份当前源码，并为回退保留旧镜像。
tar -czf /tmp/sora-source-before-redesign.tar.gz app migrations scripts Dockerfile requirements.txt alembic.ini .dockerignore
docker image tag "$(docker compose images -q sora)" sora-console:before-redesign

unzip -o /tmp/sora-console-redesign-20260907.zip -d /opt/sora
docker compose config --quiet
docker compose build sora
docker compose run --rm --no-deps --entrypoint python sora -m unittest discover -s tests -q
docker compose up -d --no-deps --force-recreate sora
docker compose ps
docker compose logs --tail 100 sora
curl -fsS http://127.0.0.1:8088/readyz
```

本版本不增加迁移文件，容器仍按原启动流程执行已有 Alembic 迁移。不要删除数据卷。重启可能中断当时正在处理的请求；上线后检查队列及已存在任务的状态，按原有暂停/恢复功能处理需要人工恢复的任务。

更新后核对：主题切换、普通用户创建页、管理员及子管理员权限、Pod 历史记录、VEO 多图素材、批次进度、已完成文件下载和后台设置保存。上述页面核对无需发起付费视频生成。

## 回退

恢复备份源码并重新构建原版本，保持 `.env`、Compose 和全部业务数据不变；或用保留的旧镜像覆盖启动。本次没有新数据库迁移，无需降级数据库。恢复旧代码会恢复旧版渠道入口。

## 维护说明

- `app.css`：旧页面布局兼容层，移除了重复的根主题变量。
- `theme.css` / `theme.js`：统一色彩与首屏主题选择。
- `components.css` / `ui.js`：全站布局、表单反馈、确认弹窗、导航和公共交互。
- `studio.css`：生成页及登录页布局。
- 所有页面静态资源统一使用 `20260907` 版本标记。

校验范围为离线单元测试及模拟浏览器回归；本地没有执行 Docker 构建、真实 PostgreSQL 部署或付费上游生成。
