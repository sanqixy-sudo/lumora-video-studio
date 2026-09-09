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

