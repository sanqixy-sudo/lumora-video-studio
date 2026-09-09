import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.auth.routes import router
from app.core.config import settings
from app.core.security import hash_password
from app.deps import get_db


class AuthSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password = ' mock-password '
        cls.password_hash = hash_password(cls.password)

    def setUp(self):
        self.user = SimpleNamespace(id=1, username='mock-user', password_hash=self.password_hash, status='active', role='user')
        self.db = MagicMock()
        self.db.query.return_value.filter.return_value.first.return_value = self.user
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)

    def login(self, password=None):
        return self.client.post('/auth/login-browser', json={'username':'mock-user','password':self.password if password is None else password})

    def test_active_user_login_and_logout_remove_cookie(self):
        response = self.login()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['target'], '/app')
        self.assertEqual(self.client.get('/auth/me').status_code, 200)
        response = self.client.post('/auth/logout', follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers['location'], '/login')
        self.assertNotIn(settings.session_cookie_name, self.client.cookies)
        self.assertEqual(self.client.get('/auth/me').status_code, 401)

    def test_wrong_password_is_not_expired_session(self):
        response = self.login('wrong-password')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['detail'], '用户名或密码错误')
        self.assertNotIn(settings.session_cookie_name, self.client.cookies)

    def test_disabled_user_rejected_with_specific_reason(self):
        self.user.status = 'disabled'
        response = self.login()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['detail'], '账号已被禁用')

    def test_roles_keep_default_destinations(self):
        for role, target in [('admin','/admin'), ('sub_admin','/admin/usage/monthly/page'), ('user','/app')]:
            self.user.role = role
            self.assertEqual(self.login().json()['target'], target)


if __name__ == '__main__':
    unittest.main()
