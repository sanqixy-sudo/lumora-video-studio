from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_env: str = 'development'
    app_secret_key: str = 'change-me'
    access_token_expire_minutes: int = 1440
    session_cookie_name: str = 'sora_session'
    session_cookie_secure: bool = False
    database_url: str = 'postgresql+psycopg://sora:sora_password@127.0.0.1:5432/sora'
    files_upload_dir: Path = Path('/data/uploads')
    files_output_dir: Path = Path('/data/outputs')
    files_temp_dir: Path = Path('/data/temp')
    log_dir: Path = Path('/data/logs')
    key_encryption_secret_file: str = '/data/secrets/key_secret'
    default_video_model: str = 'sora-2-8s'
    default_video_seconds: int = 12
    default_video_size: str = '720x1280'
    sora_api_base_url: str = 'https://niubi.zeabur.app'
    sora_api_http_timeout: int = 120
    sora_api_status_http_timeout: int = 30
    worker_poll_interval: int = 2
    max_running_jobs: int = 3
    submit_max_attempts: int = 3
    # 下载远端视频可能在远端完成后仍短暂 502，默认拉长自动重试窗口。
    download_retry_delays_seconds: str = "0,15,30,60,120,180,300,600,900,1200"
    # 远端状态仍为 processing 时，不要过早切去下载探测；默认至少轮询 6000 秒。
    content_fallback_after_seconds: int = 6000
    public_download_token_ttl_seconds: int = 86400
    bootstrap_admin_username: str = 'sanqi'
    bootstrap_admin_password: str = ''
    reference_image_max_bytes: int = 20 * 1024 * 1024
    provider_key_failure_threshold: int = 3
    provider_key_cooldown_seconds: int = 300

    @property
    def key_secret_file(self) -> Path:
        return Path(self.key_encryption_secret_file)


settings = Settings()

