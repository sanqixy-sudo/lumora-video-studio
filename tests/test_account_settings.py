import importlib
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import create_engine, inspect

from account_settings_support import AccountTestEnvironment, NEW_PASSWORD, OLD_PASSWORD
from app.api.user.settings import _locked_user
from app.core.config import settings
from app.core.security import ALGORITHM, decode_access_token, verify_password
from app.models.tables import AuditLog, User, UserProfile
from app.services.user_admin import reset_user_password


class AccountSettingsTests(unittest.TestCase):
    def setUp(self):
        self.env = AccountTestEnvironment()
        self.addCleanup(self.env.close)
        self.client = TestClient(self.env.app)
        self.login(self.client)

    def login(self, client, username="creator", password=OLD_PASSWORD):
        response = client.post("/auth/login-browser", json={"username": username, "password": password})
        self.assertEqual(response.status_code, 200)
        return client.cookies.get(settings.session_cookie_name)

    def post(self, path, data, client=None, headers=None):
        return (client or self.client).post(
            "/app/settings/" + path + "/form", data=data,
            headers={"Origin": "http://testserver"} if headers is None else headers,
            follow_redirects=False,
        )

    def password_data(self, **changes):
        return {"current_password": OLD_PASSWORD, "new_password": NEW_PASSWORD,
                "confirm_password": NEW_PASSWORD, **changes}

    def test_profile_persists_and_escapes_name_without_changing_login(self):
        response = self.post("profile", {"display_name": '  <b>张三</b>  ', "user_id": 2, "username": "changed"})
        self.assertEqual(response.status_code, 303)
        page = self.client.get(response.headers["location"])
        self.assertIn("姓名已保存", page.text)
        self.assertIn("&lt;b&gt;张三&lt;/b&gt;", page.text)
        self.assertNotIn("<b>张三</b>", page.text)
        with self.env.Session() as db:
            self.assertEqual(db.get(UserProfile, 1).display_name, "<b>张三</b>")
            self.assertIsNone(db.get(UserProfile, 2))
            self.assertEqual(db.get(User, 1).username, "creator")
            self.assertEqual(db.get(User, 1).session_version, 0)
            self.assertEqual(db.query(AuditLog).one().actor_user_id, 1)
        self.assertEqual(self.client.get("/auth/me").status_code, 200)

    def test_invalid_names_do_not_create_profile_or_audit(self):
        for name in ["", "   ", "张", "名" * 129]:
            with self.subTest(name_length=len(name)):
                response = self.post("profile", {"display_name": name})
                self.assertEqual(response.status_code, 400)
        with self.env.Session() as db:
            self.assertIsNone(db.get(UserProfile, 1))
            self.assertEqual(db.query(AuditLog).count(), 0)
        self.assertEqual(self.post("profile", {"display_name": "名" * 128}).status_code, 303)

    def test_settings_role_and_authentication_boundaries(self):
        for username in ["admin", "reporter"]:
            client = TestClient(self.env.app)
            self.login(client, username)
            self.assertEqual(client.get("/app/settings/page").status_code, 403)
            self.assertEqual(self.post("profile", {"display_name": "测试"}, client).status_code, 403)
            self.assertEqual(self.post("password", self.password_data(), client).status_code, 403)
        anonymous = TestClient(self.env.app)
        self.assertEqual(anonymous.get("/app/settings/page", follow_redirects=False).status_code, 303)
        self.assertEqual(self.post("profile", {"display_name": "测试"}, anonymous).status_code, 401)
        self.assertEqual(self.post("password", self.password_data(), anonymous).status_code, 401)
        with self.env.Session() as db:
            db.get(User, 1).status = "disabled"
            db.commit()
        self.assertEqual(self.post("profile", {"display_name": "测试"}).status_code, 401)

    def test_menu_entry_is_only_for_ordinary_users(self):
        from types import SimpleNamespace
        from starlette.requests import Request
        template = self.env.app.state.templates.get_template("workbench/base.html")
        for role in ["user", "admin", "sub_admin"]:
            html = template.render(request=Request({"type": "http", "path": "/app", "headers": []}),
                                   current_user=SimpleNamespace(username="creator", role=role))
            self.assertEqual('href="/app/settings/page"' in html, role == "user")
            self.assertIn("账号：creator", html)

    def test_same_origin_checks_both_write_endpoints(self):
        rejected = [{}, {"Origin": "https://evil.example"}, {"Origin": "null"},
                    {"Origin": "http://testserver:81"}, {"Origin": "http://testserver.evil"},
                    {"Origin": "https://testserver"}, {"Referer": "https://evil.example"},
                    {"Origin": "http://testserver", "Sec-Fetch-Site": "cross-site"},
                    {"Origin": "null", "Referer": "http://testserver/app/settings/page"}]
        for headers in rejected:
            for path, data in [("profile", {"display_name": "新名字"}), ("password", self.password_data())]:
                with self.subTest(headers=headers, path=path):
                    self.assertEqual(self.post(path, data, headers=headers).status_code, 403)
        self.assertEqual(self.post("profile", {"display_name": "新名字"},
                                  headers={"Referer": "http://testserver/app/settings/page"}).status_code, 303)
        self.assertEqual(self.post("profile", {"display_name": "另一个名字"},
                                  headers={"Origin": "http://testserver:80"}).status_code, 303)

    def test_password_validation_keeps_hash_version_and_audit_unchanged(self):
        cases = [
            {"current_password": ""}, {"current_password": "incorrect-secret"},
            {"new_password": "short", "confirm_password": "short"},
            {"confirm_password": "different-secret"},
            {"new_password": "中" * 25, "confirm_password": "中" * 25},
            {"new_password": "a" * 73, "confirm_password": "a" * 73},
            {"new_password": OLD_PASSWORD, "confirm_password": OLD_PASSWORD},
        ]
        with self.env.Session() as db:
            before = db.get(User, 1).password_hash
        for changes in cases:
            with self.subTest(changes=list(changes)):
                response = self.post("password", self.password_data(**changes))
                self.assertEqual(response.status_code, 400)
                for secret in [OLD_PASSWORD, NEW_PASSWORD, "incorrect-secret", "different-secret"]:
                    self.assertNotIn(secret, response.text)
        with self.env.Session() as db:
            self.assertEqual(db.get(User, 1).password_hash, before)
            self.assertEqual(db.get(User, 1).session_version, 0)
            self.assertEqual(db.query(AuditLog).count(), 0)

    def test_change_password_invalidates_two_sessions_and_bearer_and_keeps_spaces(self):
        first_token = self.client.cookies.get(settings.session_cookie_name)
        second = TestClient(self.env.app)
        second_token = self.login(second)
        other = TestClient(self.env.app)
        self.login(other, "other")
        response = self.post("password", self.password_data())
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login?notice=password_changed")
        self.assertNotIn(settings.session_cookie_name, self.client.cookies)
        self.assertIn("密码已修改，请使用新密码重新登录", self.client.get(response.headers["location"]).text)
        self.assertEqual(second.get("/auth/me").status_code, 401)
        for token in [first_token, second_token]:
            self.assertEqual(self.client.get("/auth/me", headers={"Authorization": "Bearer " + token}).status_code, 401)
            self.assertEqual(self.client.get("/optional-user", headers={"Authorization": "Bearer " + token}).json(), {"id": None})
        self.assertEqual(second.get("/", follow_redirects=False).headers["location"], "/login")
        self.assertEqual(second.get("/login").status_code, 200)
        self.assertEqual(other.get("/auth/me").status_code, 200)
        for password in [OLD_PASSWORD, NEW_PASSWORD.strip()]:
            self.assertEqual(self.client.post("/auth/login-browser", json={"username": "creator", "password": password}).status_code, 401)
        token = self.login(self.client, password=NEW_PASSWORD)
        self.assertEqual(decode_access_token(token)["session_version"], 1)
        self.assertEqual(self.client.get("/auth/me").status_code, 200)
        with self.env.Session() as db:
            audit = db.query(AuditLog).one()
            self.assertEqual(audit.action, "change_own_password")
            self.assertEqual(audit.actor_user_id, 1)
            self.assertIsNone(audit.detail_json)

    def test_exact_bcrypt_byte_limit_is_accepted(self):
        password = "中" * 24
        self.assertEqual(self.post("password", self.password_data(new_password=password, confirm_password=password)).status_code, 303)
        self.login(self.client, password=password)

    def test_admin_reset_also_revokes_existing_credentials(self):
        token = self.client.cookies.get(settings.session_cookie_name)
        with self.env.Session() as db:
            reset_user_password(db, db.get(User, 1), NEW_PASSWORD, 3)
            db.commit()
        self.assertEqual(self.client.get("/auth/me").status_code, 401)
        self.assertEqual(self.client.get("/optional-user", headers={"Authorization": "Bearer " + token}).json(), {"id": None})
        self.login(self.client, password=NEW_PASSWORD)

    def test_legacy_tokens_and_invalid_versions(self):
        payload = {"sub": "creator", "exp": datetime.now(UTC) + timedelta(hours=1)}
        legacy = jwt.encode(payload, settings.app_secret_key, algorithm=ALGORITHM)
        self.assertEqual(self.client.get("/auth/me", headers={"Authorization": "Bearer " + legacy}).status_code, 200)
        for version in [None, True, "0", -1, 1]:
            token = jwt.encode({**payload, "session_version": version}, settings.app_secret_key, algorithm=ALGORITHM)
            self.assertEqual(self.client.get("/auth/me", headers={"Authorization": "Bearer " + token}).status_code, 401)
        self.post("password", self.password_data())
        self.assertEqual(self.client.get("/auth/me", headers={"Authorization": "Bearer " + legacy}).status_code, 401)

    def test_stale_user_cannot_overwrite_a_new_password(self):
        with self.env.Session() as stale_db:
            stale = stale_db.get(User, 1)
            with self.env.Session() as fresh_db:
                reset_user_password(fresh_db, fresh_db.get(User, 1), NEW_PASSWORD, 3)
                fresh_db.commit()
            with self.assertRaises(HTTPException) as error:
                _locked_user(stale_db, stale)
            self.assertEqual(error.exception.status_code, 401)
        with self.env.Session() as db:
            self.assertTrue(verify_password(NEW_PASSWORD, db.get(User, 1).password_hash))
            self.assertEqual(db.get(User, 1).session_version, 1)

    def test_password_transaction_rolls_back_on_audit_failure(self):
        with patch("app.api.user.settings.write_audit", side_effect=RuntimeError("test failure")):
            with self.assertRaises(RuntimeError):
                self.post("password", self.password_data())
        with self.env.Session() as db:
            self.assertTrue(verify_password(OLD_PASSWORD, db.get(User, 1).password_hash))
            self.assertEqual(db.get(User, 1).session_version, 0)

    def test_form_and_api_login_sign_current_version(self):
        self.post("password", self.password_data())
        response = self.client.post("/auth/login", json={"username": "creator", "password": NEW_PASSWORD})
        token = response.json()["access_token"]
        self.assertEqual(decode_access_token(token)["session_version"], 1)
        response = self.client.post("/auth/login-form", data={"username": "creator", "password": NEW_PASSWORD}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(decode_access_token(self.client.cookies.get(settings.session_cookie_name))["session_version"], 1)

    def test_registration_signs_the_created_account_version(self):
        with self.env.Session() as db:
            user = db.get(User, 2)
            user.session_version = 7
            db.commit()
        anonymous = TestClient(self.env.app)
        with patch("app.api.auth.routes.get_system_setting_bool", return_value=True), patch(
            "app.api.auth.routes.create_user_with_wallet", return_value=user
        ):
            response = anonymous.post("/auth/register-form", data={
                "display_name": "新用户", "username": "other", "password": OLD_PASSWORD
            }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        token = anonymous.cookies.get(settings.session_cookie_name)
        self.assertEqual(decode_access_token(token)["session_version"], 7)
        self.assertEqual(anonymous.get("/auth/me").status_code, 200)


class SessionVersionMigrationTests(unittest.TestCase):
    def test_migration_preserves_existing_users_and_sets_default(self):
        migration = importlib.import_module("migrations.versions.0023_user_session_version")
        engine = create_engine("sqlite://")
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")
            connection.exec_driver_sql("INSERT INTO users VALUES (1, 'existing')")
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                self.assertEqual(connection.exec_driver_sql("SELECT session_version FROM users").scalar(), 0)
                connection.exec_driver_sql("INSERT INTO users (id, username) VALUES (2, 'new')")
                self.assertEqual(connection.exec_driver_sql("SELECT session_version FROM users WHERE id=2").scalar(), 0)
                migration.downgrade()
                self.assertNotIn("session_version", [column["name"] for column in inspect(connection).get_columns("users")])
                self.assertEqual(connection.exec_driver_sql("SELECT count(*) FROM users").scalar(), 2)
        engine.dispose()


    def test_alembic_upgrades_github_and_nas_database_histories(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from alembic import command
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        self.assertEqual(ScriptDirectory.from_config(config).get_heads(), ["0025_job_regeneration"])
        for revision in ["0022_upstream_errors", "0023_model_quota_costs", "0023_user_session_version"]:
            with self.subTest(revision=revision), TemporaryDirectory() as directory:
                url = "sqlite:///" + str(Path(directory) / "migration.sqlite")
                engine = create_engine(url)
                with engine.begin() as connection:
                    connection.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")
                    connection.exec_driver_sql("INSERT INTO users VALUES (1, 'existing')")
                    connection.exec_driver_sql("CREATE TABLE jobs (id INTEGER PRIMARY KEY)")
                    connection.exec_driver_sql("CREATE TABLE provider_keys (id INTEGER PRIMARY KEY)")
                    connection.exec_driver_sql("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)")
                    connection.exec_driver_sql("INSERT INTO alembic_version VALUES (?)", (revision,))
                    with Operations.context(MigrationContext.configure(connection)):
                        if revision == "0023_model_quota_costs":
                            importlib.import_module("migrations.versions.0023_model_quota_costs").upgrade()
                        elif revision == "0023_user_session_version":
                            importlib.import_module("migrations.versions.0023_user_session_version").upgrade()
                with patch.object(settings, "database_url", url):
                    command.upgrade(config, "head")
                with engine.connect() as connection:
                    self.assertEqual(connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar(),
                                     "0025_job_regeneration")
                    self.assertEqual(connection.exec_driver_sql("SELECT session_version FROM users WHERE id=1").scalar(), 0)
                    self.assertIn("retry_of_job_id", [column["name"] for column in inspect(connection).get_columns("jobs")])
                    self.assertIn("quota_cost", [column["name"] for column in inspect(connection).get_columns("jobs")])
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
