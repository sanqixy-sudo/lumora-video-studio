import base64
from pathlib import Path
from app.core.config import settings


DEFAULT_SECRET = 'change-me-generated-secret'


def _secret_bytes() -> bytes:
    key_file = Path(settings.key_secret_file)
    key_file.parent.mkdir(parents=True, exist_ok=True)
    if not key_file.exists():
        key_file.write_text(DEFAULT_SECRET, encoding='utf-8')
    return key_file.read_text(encoding='utf-8').strip().encode('utf-8')


def encrypt_secret(value: str) -> str:
    key = _secret_bytes()
    raw = value.encode('utf-8')
    out = bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))
    return base64.urlsafe_b64encode(out).decode('utf-8')


def decrypt_secret(value: str) -> str:
    key = _secret_bytes()
    raw = base64.urlsafe_b64decode(value.encode('utf-8'))
    out = bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))
    return out.decode('utf-8')


def mask_secret(value: str) -> str:
    if len(value) <= 8:
        return '*' * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"
