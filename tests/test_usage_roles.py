import io
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from jinja2 import Environment, FileSystemLoader, select_autoescape
from app.api.admin import routes
from app.deps import get_current_user, get_db
from scripts import render_ui_snapshots as fixtures
from scripts.preview_usage import build_usage_preview

ROOT = Path(__file__).resolve().parents[1]


def render_role(role):
    env = Environment(loader=FileSystemLoader(ROOT/'app/templates'), autoescape=select_autoescape(['html']))
    env.globals.update(status_label=fixtures.status_label, role_label=fixtures.role_label, user_display_name=fixtures.user_display_name)
    env.filters.update(dt=fixtures.dt, dt_full=fixtures.dt)
    user = SimpleNamespace(**{**vars(fixtures.admin), 'role': role})
    data = build_usage_preview(fixtures.user, '2026-05')
    return env.get_template('admin/usage_monthly.html').render(**{
        **fixtures.common, **data, 'current_user': user, 'can_manage': role == 'admin',
        'request': fixtures.request('/admin/usage/monthly/page'),
    })


class UsageRoleTests(unittest.TestCase):
    def test_subadmin_html_omits_adjustment_details(self):
        html = render_role('sub_admin')
        for private in ['真实', '已修改', '已调整', '模拟调整', 'data-real=', 'usage-override', 'usage-edit-btn', 'usage-modal']:
            self.assertNotIn(private, html)
        self.assertIn('本月使用', html)
        self.assertIn('2026-05', html)
        self.assertIn('导出 XLSX', html)

    def test_admin_keeps_adjustments_and_editor(self):
        html = render_role('admin')
        for expected in ['真实', '已修改', '已调整', 'data-real=', 'usage-override', 'usage-edit-btn', 'usage-modal']:
            self.assertIn(expected, html)

    def test_subadmin_json_export_and_write_permissions(self):
        app = FastAPI()
        app.include_router(routes.router)
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=3, role='sub_admin')
        app.dependency_overrides[get_db] = lambda: None
        data = build_usage_preview(fixtures.user, '2026-05')
        data['rows'] = [vars(row) for row in data['rows']]
        for row in data['rows']:
            for index, day in enumerate(row['daily'], 1):
                day['day'] = index
        client = TestClient(app)
        prefix = routes.router.prefix
        with patch.object(routes, '_usage_month_data', return_value=data) as read:
            response = client.get(prefix+'/usage/monthly?month=2026-05')
            self.assertEqual(response.status_code, 200)
            read.assert_called_once_with(None, 2026, 5, True)
            for private in ['monthly_real', 'real_total', 'override_count', 'is_override', 'note']:
                self.assertNotIn(private, response.text)
            self.assertEqual(response.json()['rows'][0]['daily'][2]['display'], 38)
            export = client.get(prefix+'/usage/monthly/export?month=2026-05')
            self.assertEqual(export.status_code, 200)
            with zipfile.ZipFile(io.BytesIO(export.content)) as archive:
                sheet = archive.read('xl/worksheets/sheet1.xml').decode()
                self.assertNotIn('真实', sheet)
                self.assertNotIn('调整', sheet)
        for endpoint in ['daily-override/form', 'daily-override/delete/form']:
            response = client.post(prefix+'/usage/'+endpoint, data={'user_id':2, 'usage_date':'2026-05-03', 'override_count':77})
            self.assertEqual(response.status_code, 403)


if __name__ == '__main__':
    unittest.main()
