# NAS video download recovery and proxy

Video downloads use a separate worker-owned pool (`VIDEO_DOWNLOAD_CONCURRENCY`, default 10, allowed range 1–32), so slow file transfers cannot exhaust status-polling threads. Each transfer attempt has a 120-second deadline. Partial responses are retained for HTTP Range retries; an OS file lock prevents two processes writing the same partial file. Only a complete transfer is renamed to the published video path.

## Web settings

Super administrators can open **System Settings** (`/admin/settings/page`) to control:

- **Proxy settings:** independent, site-wide upstream request and video download proxies. Each has a Direct / Proxy switch and supports HTTP, HTTPS, SOCKS5 and SOCKS5H URLs with an explicit port. Request proxy covers submission, polling and reference-image requests; download proxy covers video file transfers and remote streaming.
- **Concurrency:** video download concurrency (1–32), site-wide generation concurrency and existing user limits. The worker observes download concurrency within its next scheduling cycle. Lowering the limit lets current downloads finish; raising it allows more pending files to start.
- **Channel generation concurrency:** the existing per-channel limits, managed together in a separate form. These compose with global and user generation limits; they do not control file downloads.

Save each form independently. Proxy changes apply to subsequent requests/downloads; active transfers retain their initial route. Selecting Direct explicitly disables environment proxies. An empty address preserves the saved address; use the Direct switch to disable it. Credential-bearing URLs are encrypted at rest, masked in the settings view and audit trail, and not returned to the browser. Keep `/data/secrets` with database backups so encrypted settings remain readable.

The deployment variables `UPSTREAM_REQUEST_PROXY`, `VIDEO_DOWNLOAD_PROXY` and `VIDEO_DOWNLOAD_CONCURRENCY` provide initial defaults only when no database setting exists. Saved settings take precedence and survive container upgrades. Web changes do **not** require a restart; changes to initial deployment environment variables require recreating the container. No schema migration is needed for this feature.

Web retry actions hand downloads back to the worker instead of creating another download pool. Download and status-polling pools remain isolated. The runtime requires curl (installed by the Dockerfile) and `httpx[socks]` for SOCKS requests. Higher concurrency can share the same proxy bandwidth and does not guarantee faster individual transfers.

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

If the Docker bridge subnet changes, update both the socket's `ListenStream` and the saved download proxy address (and its environment fallback), then restart the socket and recreate the application container. This setup depends on the NAS v2 service, not a desktop proxy.

## Incident evidence

All 16 processor threads were waiting in video network reads while 15 submitted tasks received no status queries. The watchdog discarded running futures without terminating their threads, allowing duplicate work to accumulate. Download retries also bypassed the configured delay whenever an upstream-completed event existed.

NAS direct video transfer measured around 5 KB/s with timeouts and incomplete reads. The relevant HTTP dependency versions were identical in the pre-UI and deployed images. After thread isolation, all 15 pending upstream statuses returned completed. The NAS v2 path successfully transferred a 256 KiB range in under two seconds; the container bridge path was also verified.

Recovery retains existing upstream task IDs; do not regenerate these jobs to repair local downloads. Database/image/source backups are under `/vol1/1000/docker/lumora-worker-incident-20260921` on this NAS. Keep signed source URLs and credentials out of diagnostic output.
