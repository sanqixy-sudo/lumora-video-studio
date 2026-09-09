from contextlib import asynccontextmanager
from pathlib import Path
import random

from urllib.parse import quote

from fastapi import FastAPI, Request, Depends
from fastapi.responses import JSONResponse, RedirectResponse, FileResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from app.api.admin.routes import router as admin_router
from app.api.auth.routes import router as auth_router
from app.api.files.routes import router as files_router
from app.api.user.routes import router as user_router
from app.core.config import settings
from app.core.security import decode_access_token
from app.db import SessionLocal
from app.deps import get_db
from app.models.tables import User, Job, JobFile
from app.services.bootstrap import ensure_bootstrap_admin, ensure_dirs
from app.core.timezone import format_shanghai_datetime, format_shanghai_datetime_short
from app.services.jobs import status_label
from app.services.quota_plans import quota_plan_period_label
from app.services.system_settings import get_system_setting_bool
from app.services.user_admin import user_display_name


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_dirs()
    db = SessionLocal()
    try:
        ensure_bootstrap_admin(db)
    finally:
        db.close()
    yield



def role_label(role: str | None) -> str:
    return {"admin": "Admin", "sub_admin": "Sub Admin", "user": "User"}.get(str(role or ""), str(role or "-"))


def _safe_next(next_url: str | None) -> str | None:
    if not next_url:
        return None
    next_url = str(next_url).strip()
    if not next_url.startswith("/") or next_url.startswith("//"):
        return None
    if next_url.startswith("/auth/") or next_url.startswith("/login"):
        return None
    return next_url


def _request_next_path(request: Request) -> str:
    path = request.url.path
    if request.url.query:
        path = f"{path}?{request.url.query}"
    return path


def _wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        return True
    if request.method == "GET":
        path = request.url.path
        if path in {"/", "/admin", "/app"} or path.endswith("/page"):
            return True
    return False


app = FastAPI(title="流光 Lumora", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(Path(__file__).resolve().parent / "static")), name="static")
app.state.templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
app.state.templates.env.globals["status_label"] = status_label
app.state.templates.env.globals["role_label"] = role_label
app.state.templates.env.globals["user_display_name"] = user_display_name
app.state.templates.env.globals["quota_plan_period_label"] = quota_plan_period_label
app.state.templates.env.filters["dt"] = format_shanghai_datetime_short
app.state.templates.env.filters["dt_full"] = format_shanghai_datetime


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 401 and _wants_html(request):
        next_path = _request_next_path(request)
        return RedirectResponse(f"/login?next={quote(next_path, safe='')}&expired=1", status_code=303)
    if exc.status_code == 403 and _wants_html(request):
        return app.state.templates.TemplateResponse(
            request,
            "errors/403.html",
            {"request": request, "app_name": app.title},
            status_code=403,
        )
    headers = getattr(exc, "headers", None)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=headers)


def _home_for_cookie(request: Request) -> str | None:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        return None
    try:
        payload = decode_access_token(token)
        username = payload.get("sub")
    except Exception:
        return None
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == username, User.status == "active").first()
        if not user:
            return None
        if user.role == "admin":
            return "/admin"
        if user.role == "sub_admin":
            return "/admin/usage/monthly/page"
        return "/app"


@app.get("/")
def index(request: Request):
    target = _home_for_cookie(request)
    return RedirectResponse(target or "/login", status_code=303)


@app.get("/login-wall/{file_id}/poster")
def login_wall_poster(file_id: int, db = Depends(get_db)):
    row = (db.query(JobFile, Job, User).join(Job, Job.id == JobFile.job_id).join(User, User.id == Job.user_id).filter(JobFile.id == file_id, JobFile.file_type == 'output_video', Job.status == 'completed', User.showcase_enabled.is_(True)).first())
    if not row: return JSONResponse({'detail':'Not found'}, status_code=404)
    file, _, _ = row; path=Path(file.file_path); poster=path.with_name(f'{path.stem}_poster.jpg')
    if not poster.is_file(): return JSONResponse({'detail':'Not found'}, status_code=404)
    return FileResponse(poster, media_type='image/jpeg', headers={'Cache-Control':'public, max-age=60'})


_login_wall_cache = (0.0, [])

def _random_login_wall(db):
    global _login_wall_cache
    now = __import__('time').monotonic()
    if now - _login_wall_cache[0] < 30 and _login_wall_cache[1]:
        return list(_login_wall_cache[1])
    rows = (db.query(JobFile.id, Job.size).join(Job, Job.id == JobFile.job_id).join(User, User.id == Job.user_id).filter(Job.status == 'completed', User.showcase_enabled.is_(True), JobFile.file_type == 'output_video').order_by(Job.updated_at.desc()).limit(240).all())
    items = [{'src': f'/login-wall/{fid}/poster', 'width': 1280 if size == '1280x720' else 720, 'height': 720 if size == '1280x720' else 1280} for fid, size in rows]
    fallback = [{"src": f"/static/login-materials/public-cover-{i:02d}.webp", "width": 640, "height": 720} for i in range(24)]
    # Keep a visible local mix so unusable remote posters never fill the wall.
    items = fallback[:12] + items[:16]
    random.SystemRandom().shuffle(items)
    chosen = items[:28]
    if chosen:
        _login_wall_cache = (now, chosen)
    return chosen


@app.get("/login")
def login_page(request: Request):
    next_url = _safe_next(request.query_params.get("next"))
    target = _home_for_cookie(request)
    if target:
        return RedirectResponse(next_url or target, status_code=303)
    login_notice = "登录已过期，请重新登录。" if request.query_params.get("expired") else None
    db = SessionLocal()
    try:
        registration_enabled = get_system_setting_bool(db, "registration_enabled", False)
        login_wall_images = _random_login_wall(db)
    finally:
        db.close()
    return app.state.templates.TemplateResponse(
        request,
        "login.html",
        {
            "request": request,
            "app_name": app.title,
            "login_error": request.query_params.get("error"),
            "login_notice": login_notice,
            "registration_enabled": registration_enabled,
            "prefill_username": request.query_params.get("username", ""),
            "next_url": next_url or "",
            "login_wall_images": login_wall_images,
        },
    )


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    with SessionLocal() as db:
        db.execute(text("SELECT 1"))
    return {"status": "ready"}


app.include_router(auth_router)
app.include_router(user_router)
app.include_router(admin_router)
app.include_router(files_router)

