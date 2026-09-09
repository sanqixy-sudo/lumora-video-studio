from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.tables import QuotaLedger, QuotaWallet, User, UserProfile
from app.services.audit import write_audit


VALID_ROLES = {"user", "sub_admin", "admin"}


def user_display_name(user: User | None) -> str:
    if not user:
        return "-"
    value = str(getattr(user, "display_name", "") or "").strip()
    return value or str(user.username or "")


def profile_map_for_users(db: Session, users: list[User]) -> dict[int, UserProfile]:
    user_ids = sorted({int(user.id) for user in users if user and user.id is not None})
    if not user_ids:
        return {}
    rows = db.query(UserProfile).filter(UserProfile.user_id.in_(user_ids)).all()
    return {int(row.user_id): row for row in rows}


def attach_display_names(db: Session, users: list[User]) -> dict[int, UserProfile]:
    profiles = profile_map_for_users(db, users)
    for user in users:
        profile = profiles.get(int(user.id)) if user and user.id is not None else None
        setattr(user, "display_name", (profile.display_name or "").strip() if profile else "")
    return profiles


def set_user_display_name(db: Session, user: User, display_name: str | None, actor_user_id: int | None) -> UserProfile:
    value = (display_name or "").strip()[:128] or None
    profile = db.query(UserProfile).filter(UserProfile.user_id == user.id).first()
    if not profile:
        profile = UserProfile(user_id=user.id)
    profile.display_name = value
    db.add(profile)
    setattr(user, "display_name", value or "")
    write_audit(db, actor_user_id, "update_user_display_name", "user", user.id, {"display_name": value})
    return profile


def create_user_with_wallet(db: Session, username: str, password: str, role: str = "user", display_name: str | None = None) -> User:
    username = " ".join(str(username or "").split())
    if len(username) < 3 or len(username) > 64:
        raise ValueError("用户名需为 3-64 个字符")
    if len(str(password or "")) < 6:
        raise ValueError("密码至少 6 位")
    if role not in VALID_ROLES:
        raise ValueError("角色无效")
    if db.query(User).filter(User.username == username).first():
        raise ValueError("用户名已存在")
    user = User(username=username, password_hash=hash_password(password), role=role, status="active", showcase_enabled=False)
    db.add(user)
    db.flush()
    db.add(QuotaWallet(user_id=user.id, remaining_quota=0, total_granted=0, total_used=0, reserved_quota=0))
    if (display_name or "").strip():
        set_user_display_name(db, user, display_name, None)
    return user


def set_user_status(db: Session, user: User, status: str, actor_user_id: int | None) -> None:
    user.status = status
    db.add(user)
    write_audit(db, actor_user_id, "set_user_status", "user", user.id, {"status": status})


def set_user_role(db: Session, user: User, role: str, actor_user_id: int | None) -> None:
    if role not in VALID_ROLES:
        raise ValueError("角色无效")
    old_role = user.role
    user.role = role
    db.add(user)
    write_audit(db, actor_user_id, "set_user_role", "user", user.id, {"old_role": old_role, "role": role})


def set_user_showcase(db: Session, user: User, enabled: bool, actor_user_id: int | None) -> None:
    user.showcase_enabled = enabled
    db.add(user)
    write_audit(db, actor_user_id, "set_user_showcase", "user", user.id, {"showcase_enabled": enabled})


def reset_user_password(db: Session, user: User, password: str, actor_user_id: int | None) -> None:
    user.password_hash = hash_password(password)
    db.add(user)
    write_audit(db, actor_user_id, "reset_password", "user", user.id, None)


def grant_quota(db: Session, user: User, amount: int, operator_user_id: int | None, note: str | None = None) -> QuotaWallet:
    wallet = db.query(QuotaWallet).filter(QuotaWallet.user_id == user.id).with_for_update().first()
    if not wallet:
        wallet = QuotaWallet(user_id=user.id, remaining_quota=0, total_granted=0, total_used=0)
        db.add(wallet)
        db.flush()
    wallet.remaining_quota += amount
    wallet.total_granted += amount
    db.add(wallet)
    db.add(QuotaLedger(user_id=user.id, change_amount=amount, action="grant_manual", note=note, operator_user_id=operator_user_id))
    write_audit(db, operator_user_id, "grant_quota", "user", user.id, {"amount": amount, "note": note})
    return wallet


def deduct_quota(db: Session, user: User, amount: int, operator_user_id: int | None, note: str | None = None) -> QuotaWallet:
    wallet = db.query(QuotaWallet).filter(QuotaWallet.user_id == user.id).with_for_update().first()
    if not wallet:
        raise ValueError("额度钱包不存在")
    if int(wallet.remaining_quota or 0) - int(wallet.reserved_quota or 0) < amount:
        raise ValueError("可用额度不足")
    wallet.remaining_quota -= amount
    db.add(wallet)
    db.add(QuotaLedger(user_id=user.id, change_amount=-amount, action="deduct_manual", note=note, operator_user_id=operator_user_id))
    write_audit(db, operator_user_id, "deduct_quota", "user", user.id, {"amount": amount, "note": note})
    return wallet
