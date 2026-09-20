from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.security import decode_access_token, session_version_matches
from app.db import SessionLocal
from app.models.tables import User
from app.services.user_admin import attach_display_names


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


def user_for_token(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    try:
        payload = decode_access_token(token)
        subject = payload['sub']
    except (ValueError, KeyError, TypeError):
        return None
    user = db.query(User).filter(User.username == subject).first()
    if not user or user.status != 'active' or not session_version_matches(payload, user):
        return None
    return user


def get_current_user(
    authorization: str | None = Header(default=None),
    cookie_token: str | None = Cookie(default=None, alias=settings.session_cookie_name),
    db: Session = Depends(get_db),
) -> User:
    user = user_for_token(db, _extract_token(authorization, cookie_token))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid or expired session')
    if user.role == 'user':
        attach_display_names(db, [user])
    return user


def get_optional_user(
    authorization: str | None = Header(default=None),
    cookie_token: str | None = Cookie(default=None, alias=settings.session_cookie_name),
    db: Session = Depends(get_db),
) -> User | None:
    return user_for_token(db, _extract_token(authorization, cookie_token))


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
