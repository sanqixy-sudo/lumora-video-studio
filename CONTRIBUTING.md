# 开发说明

本地开发需要 Python 3.11+、PostgreSQL 和 FFmpeg。先复制 `.env.example` 为 `.env`，设置数据库、管理员密码、会话密钥和本地可写的数据目录。

```bash
python -m venv .venv
```

激活虚拟环境后执行：

```bash
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8088
```

需要处理任务时另开终端运行 `python -m app.workers.main`。

## 目录结构

```text
app/
  api/                 # 页面与接口路由
  services/            # 业务服务与任务处理
  static/              # 公共资源、主题和页面样式
  templates/           # Jinja2 页面模板
migrations/            # 数据库迁移
scripts/               # 运维与检查脚本
docker-compose.yml     # 容器编排
Dockerfile             # 镜像构建
```


## 个人设置与登录版本

普通用户可从右上角账户菜单进入个人设置，修改显示姓名和密码。改密和管理员重置密码都会使该账号的全部旧登录凭证失效，后台生成任务继续运行。

部署此功能前先执行 `alembic upgrade head`，新增用户 `session_version` 字段，再启动新版 Web 与 Worker；Docker 启动脚本已按此顺序执行。存量登录凭证按版本 0 兼容，直到账号修改密码。

个人设置写接口校验 Origin（缺失时使用 Referer）。反向代理应保留外部 Host，并正确传递协议，Uvicorn 仅信任受控代理的转发头。

验证个人设置可运行 `python -m unittest discover -s tests -p "test_*.py"`。浏览器验收运行 `node tests/account_settings_browser.cjs`（需要 Playwright，可用 `SORA_PLAYWRIGHT` 指定模块位置、`SORA_TEST_PYTHON` 指定 Python）。脚本会启动隔离 SQLite 测试服务，退出时关闭服务，截图保存在 `runtime/account-settings/`，不连接业务数据库或上游生成服务。

旧 NAS 数据库可能停留在 `0023_model_quota_costs`。仓库保留该历史迁移，并通过 `0024_merge_account_legacy_quota` 合并为单一迁移头；无需手动修改或重置 `alembic_version`，也不会删除历史额度字段。
