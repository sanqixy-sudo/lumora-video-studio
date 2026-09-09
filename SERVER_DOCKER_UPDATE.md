# Wuyin Omni Docker 服务器更新

本更新包以 `原版` 镜像源码为基线，恢复原 `veo_omni` 的独立多素材调用，并新增独立的 `wuyin_omni` 渠道。两个渠道的接口和素材数量分别处理；原有密钥、额度、数据库和历史任务均不会被替换或重置。

旧的 v1、v2、v3 更新包已经作废，请勿再使用：

- `sora-google-omni-docker-update-20260806.zip`
- `sora-google-omni-docker-update-20260806-v2.zip`
- `sora-wuyin-omni-docker-update-20260806-v3.zip`

本次使用：

- `sora-wuyin-omni-docker-update-20260806-v4.zip`
- `sora-wuyin-omni-docker-update-20260806-v4.zip.sha256`

以下示例假设服务器项目目录为 `/opt/sora`，Compose 服务名为 `sora`。

```bash
cd /tmp
sha256sum -c sora-wuyin-omni-docker-update-20260806-v4.zip.sha256

cd /opt/sora
cp docker-compose.yml "docker-compose.yml.bak.$(date +%Y%m%d_%H%M%S)"
unzip -o /tmp/sora-wuyin-omni-docker-update-20260806-v4.zip -d /opt/sora

docker compose config
docker compose build sora
docker compose up -d --no-deps --force-recreate sora
docker compose ps
docker compose logs --tail 100 sora
curl -fsS http://127.0.0.1:8088/readyz
```

更新后不要修改原有 `veo_omni` 密钥。首页选择原 VEO Omni 时显示 6 图素材框，支持 `Ingredients_images` 多图模式以及单个 `video_url` 视频编辑模式。

需要在后台新增一条渠道时，选择 `Wuyin Omni`，填写无印 API 密钥；接口地址会使用 `https://api.wuyinkeji.com`。首页选择 Wuyin Omni 时显示 1 图 + 1 视频素材框，并按无印接口分别提交单个 `images` 和 `video` URL。

不要执行 `docker compose down -v`，否则可能删除数据库数据卷。
