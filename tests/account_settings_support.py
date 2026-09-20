"""Isolated account database/app for tests and local browser verification."""
from pathlib import Path
from unittest.mock import patch

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.exceptions import HTTPException

from app import main
from app.api.auth.routes import router as auth_router
from app.api.user.settings import router as settings_router
from app.core.security import hash_password
from app.deps import get_db, get_optional_user
from app.models.tables import User, UserProfile

ROOT = Path(__file__).resolve().parents[1]
OLD_PASSWORD = " old-password "
NEW_PASSWORD = " new-password "


class AccountTestEnvironment:
    def __init__(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        User.__table__.create(self.engine)
        UserProfile.__table__.create(self.engine)
        # SQLite uses INTEGER for generated IDs and JSON in place of PostgreSQL JSONB.
        with self.engine.begin() as connection:
            connection.exec_driver_sql("""CREATE TABLE audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, actor_user_id BIGINT, action VARCHAR(64) NOT NULL,
                target_type VARCHAR(32) NOT NULL, target_id BIGINT, detail_json JSON,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)""")
        self.Session = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)
        with self.Session() as db:
            password_hash = hash_password(OLD_PASSWORD)
            db.add_all([User(id=i, username=name, password_hash=password_hash, role=role, status="active")
                        for i, name, role in [(1, "creator", "user"), (2, "other", "user"),
                                              (3, "admin", "admin"), (4, "reporter", "sub_admin")]])
            db.commit()
        self.app = FastAPI()
        self.app.state.templates = main.app.state.templates
        self.app.include_router(auth_router)
        self.app.include_router(settings_router)
        self.app.add_api_route("/", main.index, methods=["GET"])
        self.app.add_api_route("/login", main.login_page, methods=["GET"])
        self.app.add_exception_handler(HTTPException, main.http_exception_handler)
        self.app.mount("/static", StaticFiles(directory=ROOT / "app/static"), name="static")

        def database():
            with self.Session() as db:
                yield db
        self.app.dependency_overrides[get_db] = database

        @self.app.get("/optional-user")
        def optional_user(user=Depends(get_optional_user)):
            return {"id": user.id if user else None}

        self.patches = [
            patch("app.main.SessionLocal", self.Session),
            patch("app.main._random_login_wall", return_value=[]),
            patch("app.main.get_system_setting_bool", return_value=False),
        ]
        for item in self.patches:
            item.start()

    def close(self):
        for item in reversed(self.patches):
            item.stop()
        self.engine.dispose()
