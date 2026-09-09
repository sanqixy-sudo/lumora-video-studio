from datetime import UTC, datetime
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_access_token, verify_password
from app.deps import get_current_user, get_db
from app.models.tables import User
from app.schemas import LoginRequest, TokenResponse
from app.services.system_settings import get_system_setting_bool
from app.services.user_admin import create_user_with_wallet

router = APIRouter(tags=["auth"])


def _default_target_for_user(user: User) -> str:
    if user.role == "admin":
        return "/admin"
    if user.role == "sub_admin":
        return "/admin/usage/monthly/page"
    return "/app"


def _safe_next(next_url: str | None) -> str | None:
    if not next_url:
        return None
    next_url = str(next_url).strip()
    if not next_url.startswith("/") or next_url.startswith("//"):
        return None
    if next_url.startswith("/auth/") or next_url.startswith("/login"):
        return None
    return next_url


def _target_for_user(user: User, next_url: str | None = None) -> str:
    return _safe_next(next_url) or _default_target_for_user(user)


def _set_auth_cookie(response, token: str):
    if response is None:
        return
    response.set_cookie(
        settings.session_cookie_name,
        token,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )


def _login_user(username: str, password: str, db: Session) -> tuple[User, str]:
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    if user.status != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已被禁用")
    user.last_login_at = datetime.now(UTC)
    db.add(user)
    db.commit()
    token = create_access_token(user.username)
    return user, token


@router.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    _, token = _login_user(payload.username, payload.password, db)
    return TokenResponse(access_token=token)


@router.post("/auth/login-browser")
def login_browser(payload: LoginRequest, db: Session = Depends(get_db)):
    user, token = _login_user(payload.username, payload.password, db)
    target = _target_for_user(user, getattr(payload, "next", None))
    response = JSONResponse({"ok": True, "target": target})
    _set_auth_cookie(response, token)
    return response


@router.post("/auth/login-form")
def login_form(username: str = Form(...), password: str = Form(...), next: str | None = Form(None), db: Session = Depends(get_db)):
    try:
        user, token = _login_user(username, password, db)
    except HTTPException as exc:
        error_text = "账号已被禁用" if exc.status_code == status.HTTP_403_FORBIDDEN else "用户名或密码错误"
        query_data = {"error": error_text, "username": username}
        safe_next = _safe_next(next)
        if safe_next:
            query_data["next"] = safe_next
        query = urlencode(query_data)
        return RedirectResponse(url=f"/login?{query}", status_code=303)
    target = _target_for_user(user, next)
    response = RedirectResponse(url=target, status_code=303)
    _set_auth_cookie(response, token)
    return response


@router.post("/auth/register-form")
def register_form(
    display_name: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    next: str | None = Form(None),
    db: Session = Depends(get_db),
):
    if not get_system_setting_bool(db, "registration_enabled", False):
        return RedirectResponse("/login?error=当前暂未开放注册", status_code=303)
    name = " ".join(str(display_name or "").split())
    if len(name) < 2:
        return RedirectResponse("/login?error=请填写姓名", status_code=303)
    try:
        user = create_user_with_wallet(db, username.strip(), password, "user", name)
        db.commit()
    except ValueError as exc:
        query = urlencode({"error": str(exc), "username": username})
        return RedirectResponse(f"/login?{query}", status_code=303)
    token = create_access_token(user.username)
    response = RedirectResponse(url=_target_for_user(user, next), status_code=303)
    _set_auth_cookie(response, token)
    return response


@router.post("/auth/logout")
def logout(_: Request):
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(settings.session_cookie_name, path="/")
    return response


@router.get("/auth/me")
def me(current_user: User = Depends(get_current_user)) -> dict:
    return {
        "id": current_user.id,
        "username": current_user.username,
        "role": current_user.role,
        "status": current_user.status,
    }
