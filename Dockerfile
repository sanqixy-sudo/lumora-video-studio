ARG BASE_IMAGE=public.ecr.aws/docker/library/postgres:16-bookworm
FROM ${BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH=/opt/venv/bin:$PATH

WORKDIR /app

RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i \
        -e 's|http://deb.debian.org/debian|http://mirrors.aliyun.com/debian|g' \
        -e 's|https://deb.debian.org/debian|http://mirrors.aliyun.com/debian|g' \
        -e 's|http://security.debian.org/debian-security|http://mirrors.aliyun.com/debian-security|g' \
        -e 's|https://security.debian.org/debian-security|http://mirrors.aliyun.com/debian-security|g' \
        -e 's|http://deb.debian.org/debian-security|http://mirrors.aliyun.com/debian-security|g' \
        -e 's|https://deb.debian.org/debian-security|http://mirrors.aliyun.com/debian-security|g' \
        /etc/apt/sources.list.d/debian.sources; \
    fi; \
    apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    ffmpeg \
    python3 \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./

RUN python3 -m venv /opt/venv \
    && pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

COPY . .

RUN set -eux; \
    find migrations/versions -type d -name __pycache__ -prune -exec rm -rf {} + || true; \
    find migrations/versions -maxdepth 1 -type f -name '0008*.py' \
      ! -name '0008_provider_key_ext.py' \
      ! -name '0008_api_ref_preset.py' \
      -delete; \
    chmod +x scripts/*.sh

EXPOSE 8000

CMD ["bash", "-lc", "scripts/start_single_container.sh"]
