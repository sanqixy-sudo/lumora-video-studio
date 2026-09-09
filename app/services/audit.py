from sqlalchemy.orm import Session
from app.models.tables import AuditLog


def write_audit(db: Session, actor_user_id: int | None, action: str, target_type: str, target_id: int | None, detail_json: dict | None = None) -> None:
    db.add(AuditLog(actor_user_id=actor_user_id, action=action, target_type=target_type, target_id=target_id, detail_json=detail_json))
