from pathlib import Path
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.security import hash_password
from app.models.tables import QuotaWallet, User


def ensure_dirs() -> None:
    for path in [settings.files_upload_dir, settings.files_output_dir, settings.files_temp_dir, settings.log_dir, settings.key_secret_file.parent]:
        Path(path).mkdir(parents=True, exist_ok=True)


def ensure_bootstrap_admin(db: Session) -> None:
    user = db.query(User).filter(User.username == settings.bootstrap_admin_username).first()
    if user:
        return
    if not settings.bootstrap_admin_password.strip():
        raise ValueError("Set BOOTSTRAP_ADMIN_PASSWORD before creating the first administrator")
    admin = User(
        username=settings.bootstrap_admin_username,
        password_hash=hash_password(settings.bootstrap_admin_password),
        role='admin',
        status='active',
    )
    db.add(admin)
    db.flush()
    db.add(QuotaWallet(user_id=admin.id, remaining_quota=0, total_granted=0, total_used=0, reserved_quota=0))
    db.commit()
