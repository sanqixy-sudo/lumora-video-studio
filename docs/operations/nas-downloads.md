# NAS video download recovery and proxy

Video downloads use a separate worker-owned pool (`VIDEO_DOWNLOAD_CONCURRENCY`, default 10, allowed range 1–32), so slow file transfers cannot exhaust status-polling threads. Each transfer attempt has a 120-second deadline. Partial responses are retained for HTTP Range retries; an OS file lock prevents two processes writing the same partial file. Only a complete transfer is renamed to the published video path.

Set `VIDEO_DOWNLOAD_PROXY` in the deployment `.env` to use an HTTP or SOCKS proxy for video files only. API submission and polling keep their existing network configuration. Web retry actions hand downloads back to the worker instead of creating an additional web-side download pool. Restart the service after changing concurrency. Leave it empty for the existing default network behavior. The runtime requires curl, which is installed by the Dockerfile.

## NAS deployment on 2026-09-21

The NAS v2 HTTP proxy listens on `127.0.0.1:20171`. The Docker bridge is `172.18.0.1`. A socket-activated forwarder listens only on `172.18.0.1:20172` and forwards to that local v2 endpoint. The app setting is:

```dotenv
VIDEO_DOWNLOAD_PROXY=http://172.18.0.1:20172
VIDEO_DOWNLOAD_CONCURRENCY=10
```

The units are `/etc/systemd/system/lumora-video-proxy.socket` and `.service`. The socket is enabled for startup and ordered after Docker. Check them with:

```sh
systemctl status lumora-video-proxy.socket lumora-video-proxy.service
```

If the Docker bridge subnet changes, update both the socket's `ListenStream` and the app environment, then restart the socket and recreate the application container. This setup depends on the NAS v2 service, not a desktop proxy.

## Incident evidence

All 16 processor threads were waiting in video network reads while 15 submitted tasks received no status queries. The watchdog discarded running futures without terminating their threads, allowing duplicate work to accumulate. Download retries also bypassed the configured delay whenever an upstream-completed event existed.

NAS direct video transfer measured around 5 KB/s with timeouts and incomplete reads. The relevant HTTP dependency versions were identical in the pre-UI and deployed images. After thread isolation, all 15 pending upstream statuses returned completed. The NAS v2 path successfully transferred a 256 KiB range in under two seconds; the container bridge path was also verified.

Recovery retains existing upstream task IDs; do not regenerate these jobs to repair local downloads. Database/image/source backups are under `/vol1/1000/docker/lumora-worker-incident-20260921` on this NAS. Keep signed source URLs and credentials out of diagnostic output.
