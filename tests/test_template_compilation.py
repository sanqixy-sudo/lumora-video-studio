import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from jinja2 import Environment, FileSystemLoader
from app.api.admin.routes import reset_password_form


class TemplateRegressionTests(unittest.TestCase):
    def test_all_application_templates_compile(self):
        env = Environment(loader=FileSystemLoader(str(Path(__file__).resolve().parents[1] / "app/templates")))
        env.filters.update(dt=str, dt_full=str)
        for name in env.list_templates():
            with self.subTest(template=name):
                env.get_template(name)

    def test_password_reset_returns_password_notice(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(id=7)
        with patch("app.api.admin.routes.reset_user_password") as reset:
            response = reset_password_form(7, "test-only-password", SimpleNamespace(id=1), db)
        reset.assert_called_once()
        db.commit.assert_called_once()
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/admin/users/7/page?notice=password_reset")


if __name__ == "__main__":
    unittest.main()
