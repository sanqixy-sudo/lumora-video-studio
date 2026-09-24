<p align="center">
  <img src="app/static/brand/lumora-mark.svg" width="96" alt="Lumora Logo" />
</p>

<h1 align="center">Lumora · 流光</h1>

<p align="center">面向团队的 AI 视频创作工作台：用参考素材和批量提示词，把灵感快速变成可下载、可管理的作品。</p>

<p align="center">
  <a href="https://github.com/sanqixy-sudo/lumora-video-studio"><img src="https://img.shields.io/badge/status-active-6c63ff?style=flat-square" alt="status" /></a>
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/FastAPI-Web-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Docker-ready-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker" />
</p>

## 项目简介

Lumora 是一个基于 FastAPI、Jinja2 和原生 JavaScript 的 AI 视频创作平台。它将素材管理、批量提示词、渠道生成、任务追踪、视频预览、作品广场和后台运营放在同一个工作台中，并提供浅色、深色和移动端布局。

## 功能亮点

- **批量创作**：同一组参考素材搭配多条提示词，一次提交多个视频任务。
- **多渠道适配**：按渠道展示模型和能力，保留额度扣减、失败退回和历史任务兼容。
- **作品管理**：视频预览、下载、收藏、自用保护、筛选和当前页批量下载。
- **任务与批次**：查看处理阶段、错误原因、批次进度和本地文件就绪状态。
- **资源与额度**：参考图预设、图片链接确认、套餐、额度流水和月度用量报表。
- **管理后台**：用户、额度、任务、队列、渠道密钥、系统设置和审计记录。
- **响应式界面**：桌面侧栏、移动导航抽屉、键盘焦点管理及双主题切换。

## 技术栈

| 层级 | 技术 |
| --- | --- |
| Web | FastAPI、Jinja2、SQLAlchemy |
| 前端 | 原生 JavaScript、CSS、Heroicons |
| 数据库 | PostgreSQL 16（Docker 内置） |
| 运行 | Docker Compose |

## 快速开始

```bash
git clone https://github.com/sanqixy-sudo/lumora-video-studio.git
cd lumora-video-studio
cp .env.example .env
# 编辑 .env：设置 BOOTSTRAP_ADMIN_PASSWORD 和随机 APP_SECRET_KEY

docker compose up -d --build
```

需要 Docker Engine 和 Docker Compose v2.24+。容器内包含 PostgreSQL、Web 服务、后台 Worker 和 FFmpeg，启动时自动运行数据库迁移。

启动后访问 `http://127.0.0.1:8088`。首次部署请使用强密码并配置数据库、会话密钥和上游渠道参数。

## 配置说明

**首次启动前必须设置 `BOOTSTRAP_ADMIN_PASSWORD`**，否则不会创建管理员。账号名由 `BOOTSTRAP_ADMIN_USERNAME` 指定；已有账号的密码不会随该变量更新。

设置随机 `APP_SECRET_KEY`；若修改数据库密码，请同时更新 `POSTGRES_PASSWORD` 和 `DATABASE_URL`。HTTPS 部署可设置 `SESSION_COOKIE_SECURE=true`。

所有运行配置通过环境变量注入，示例见 [`.env.example`](.env.example)。不要把真实密钥、Cookie、数据库文件或生产媒体文件提交到仓库。

## oaire-flow omni 渠道

在管理后台“上游密钥”新增渠道，选择 **oaire-flow omni**，填写名称和 API Key；默认调用地址为 `https://api.oairegbox.cc`（可修改）。令牌需开通 `Gemini flow` 分组，模型固定为 `flow-omni-1.1-flash`，不必填写其他渠道的模型字段。

创建页面选择该渠道后，不选参考图就是文生视频；可用参考图预设或公网图片链接添加多张图（建议不超过 6 张，超过时上游可能只取前几张）。参考图提交时检查链接及图片内容是否可读取，不校验素材比例。输出约 8 秒、720p，支持横屏和竖屏；不提供视频编辑。应用仍按每条任务预留额度，上游价格和授权以供应商为准。

适配使用 JSON `POST /v1/videos`，图片通过 `images` 数组传递，不发送 `seconds`、`duration` 或视频编辑字段。Worker 使用原任务 ID 查询 `GET /v1/videos/{task_id}`；完成后优先读取 `video_url`，兼容 `data[0].url` 和 `metadata.url`，再进入现有下载队列。旧 Omni 渠道独立保留，无需数据库迁移。

协议来源：[Flow Omni 接口文档](https://docs.oairegbox.cc/#flow-omni)。本地回归：`python -m unittest discover -s tests -p "test_flow_omni_integration.py" -v`，使用隔离数据库及模拟上游，不消耗真实生成额度。

## oaire omni 渠道

在管理后台新增 **oaire omni** 渠道并填写 API Key，默认地址 `https://api.oairegbox.cc`，令牌需开通 `gemini-fast` 分组。默认模型 `omni-fast`；若使用无水印版，可在 10 秒模型 ID 填 `omni-fast-no-water`。创建页面支持纯提示词文生视频，或最多 5 张公网参考图的图生视频，不提供 V2V 和续写。图片只检查能否读取，不校验素材比例。输出约 10 秒，横竖屏由 `aspect_ratio` 指定。

使用 JSON `POST /v1/videos`（参考图为 `images` 数组），保留任务 ID 轮询 `GET /v1/videos/{task_id}`；完成后优先使用 `video_url`，兼容 `data[0].url`，沿用现有下载队列。接口依据：[OAIREGBOX Omni 文档](https://docs.oairegbox.cc/#omni)。

## 更新与数据

更新源码后执行 `docker compose up -d --build`。数据库保存在命名卷 `postgres-data`，视频、上传文件、日志及加密密钥位于 `data/`。保留这些数据；不要使用 `docker compose down -v` 删除数据库卷。

## 兼容与边界

项目保持现有页面地址、接口契约、权限、额度规则和历史数据兼容。已下线渠道不会创建新任务，历史任务仍可查询和处理；真实付费生成请在配置完成并确认额度后进行。

开发运行与目录说明见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可证

当前仓库暂未指定开源许可证。若要公开分发，请先补充 LICENSE 文件并确认上游素材和接口的使用授权。
