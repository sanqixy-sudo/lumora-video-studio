from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.security import decode_access_token
from app.db import SessionLocal
from app.models.tables import User


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _extract_token(authorization: str | None, cookie_token: str | None) -> str | None:
    if authorization and authorization.lower().startswith('bearer '):
        return authorization.split(' ', 1)[1].strip()
    return cookie_token


def get_current_user(
    authorization: str | None = Header(default=None),
    cookie_token: str | None = Cookie(default=None, alias=settings.session_cookie_name),
    db: Session = Depends(get_db),
) -> User:
    token = _extract_token(authorization, cookie_token)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Missing authentication token')
    try:
        payload = decode_access_token(token)
        subject = payload['sub']
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid token') from exc
    user = db.query(User).filter(User.username == subject).first()
    if not user or user.status != 'active':
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Inactive or missing user')
    return user


def get_optional_user(
    authorization: str | None = Header(default=None),
    cookie_token: str | None = Cookie(default=None, alias=settings.session_cookie_name),
    db: Session = Depends(get_db),
) -> User | None:
    token = _extract_token(authorization, cookie_token)
    if not token:
        return None
    try:
        payload = decode_access_token(token)
        subject = payload['sub']
    except Exception:
        return None
    return db.query(User).filter(User.username == subject, User.status == 'active').first()


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    return require_super_admin(current_user)


def require_super_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != 'admin':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Forbidden')
    return current_user


def require_admin_or_subadmin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in {'admin', 'sub_admin'}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Forbidden')
    return current_user


def is_super_admin(user: User | None) -> bool:
    return bool(user and user.role == 'admin')
