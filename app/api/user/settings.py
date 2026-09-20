"""Self-service account settings for ordinary users."""

from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.deps import get_current_user, get_db
from app.models.tables import User
from app.services.audit import write_audit
from app.services.user_admin import set_user_display_name

router = APIRouter(prefix="/app/settings", tags=["account-settings"])


def require_account_user(user: User = Depends(get_current_user)) -> User:
    if user.role != "user":
        raise HTTPException(status_code=403, detail="仅普通用户可使用个人设置")
    return user


def _origin(value: str) -> tuple[str, str, int] | None:
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return None
        return parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return None


def require_same_origin(request: Request) -> None:
    source = request.headers.get("origin")
    if source is None:
        source = request.headers.get("referer", "")
    if (request.headers.get("sec-fetch-site") == "cross-site"
            or _origin(source) is None
            or _origin(source) != _origin(str(request.base_url))):
        raise HTTPException(status_code=403, detail="请求来源无效，请刷新页面后重试")


def _locked_user(db: Session, current_user: User) -> User:
    expected_version = current_user.session_version or 0
    user = db.query(User).filter(User.id == current_user.id).populate_existing().with_for_update().first()
    if not user or user.status != "active" or user.session_version != expected_version:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    if user.role != "user":
        raise HTTPException(status_code=403, detail="仅普通用户可使用个人设置")
    return user


@router.get("/page")
def settings_page(request: Request, user: User = Depends(require_account_user)):
    return request.app.state.templates.TemplateResponse(
        request, "app/settings.html",
        {"request": request, "current_user": user,
         "profile_saved": request.query_params.get("notice") == "profile_saved"},
        headers={"Cache-Control": "no-store"},
    )


@router.post("/profile/form", dependencies=[Depends(require_same_origin)])
def save_profile(
    display_name: str = Form(""),
    user: User = Depends(require_account_user),
    db: Session = Depends(get_db),
):
    name = display_name.strip()
    if not 2 <= len(name) <= 128:
        raise HTTPException(status_code=400, detail="显示姓名需为 2–128 个字符")
    user = _locked_user(db, user)
    set_user_display_name(db, user, name, user.id)
    db.commit()
    return RedirectResponse("/app/settings/page?notice=profile_saved", status_code=303)


@router.post("/password/form", dependencies=[Depends(require_same_origin)])
def change_password(
    current_password: str = Form(""),
    new_password: str = Form(""),
    confirm_password: str = Form(""),
    user: User = Depends(require_account_user),
    db: Session = Depends(get_db),
):
    # Validate manually: validation responses must never echo password inputs.
    if not current_password:
        raise HTTPException(status_code=400, detail="请输入当前密码")
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码至少 6 位")
    if len(new_password.encode("utf-8")) > 72:
        raise HTTPException(status_code=400, detail="新密码不能超过 72 字节，请减少字符数量")
    if new_password != confirm_password:
        raise HTTPException(status_code=400, detail="两次输入的新密码不一致")
    user = _locked_user(db, user)
    if not verify_password(current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="当前密码不正确")
    if verify_password(new_password, user.password_hash):
        raise HTTPException(status_code=400, detail="新密码不能与当前密码相同")
    user.password_hash = hash_password(new_password)
    user.session_version += 1
    write_audit(db, user.id, "change_own_password", "user", user.id)
    db.commit()
    response = RedirectResponse("/login?notice=password_changed", status_code=303)
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.headers["Cache-Control"] = "no-store"
    return response
