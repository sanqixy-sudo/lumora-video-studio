import io
import unittest
import zipfile
from datetime import UTC, date, datetime
from decimal import Decimal
from xml.etree import ElementTree
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.api.admin import routes
from app.deps import get_current_user, get_db
from app.models.tables import Base, JobCost, User
from scripts import render_ui_snapshots as fixtures
from scripts.preview_usage import build_usage_preview

ROOT = Path(__file__).resolve().parents[1]


def render_role(role):
    env = Environment(loader=FileSystemLoader(ROOT/'app/templates'), autoescape=select_autoescape(['html']))
    env.globals.update(status_label=fixtures.status_label, role_label=fixtures.role_label, user_display_name=fixtures.user_display_name)
    env.filters.update(dt=fixtures.dt, dt_full=fixtures.dt)
    user = SimpleNamespace(**{**vars(fixtures.admin), 'role': role})
    data = build_usage_preview(fixtures.user, '2026-05')
    cost_report = {
        'count': 1,
        'total': '3.90',
        'pending_count': 1,
        'daily_totals': [{'date': f'2026-05-{day:02d}', 'amount': '3.90' if day == 3 else '0.00', 'count': 1 if day == 3 else 0} for day in data['days']],
        'rows': [{'user_id': 2, 'username': 'creator01', 'monthly_amount': '3.90', 'daily': [{'date': f'2026-05-{day:02d}', 'amount': '3.90' if day == 3 else '0.00', 'count': 1 if day == 3 else 0} for day in data['days']]}],
    }
    return env.get_template('admin/usage_monthly.html').render(**{
        **fixtures.common, **data, 'current_user': user, 'can_manage': role == 'admin', 'cost_report': cost_report,
        'cost_rows': {2: cost_report['rows'][0]}, 'cost_only_rows': [],
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
        self.assertIn('id="usage-view-count"', html)
        self.assertIn('id="usage-view-cost"', html)
        self.assertIn('$3.90', html)
        self.assertNotIn('/admin/costs/pending?', html)

    def test_admin_keeps_adjustments_and_editor(self):
        html = render_role('admin')
        for expected in ['真实', '已修改', '已调整', 'data-real=', 'usage-override', 'usage-edit-btn', 'usage-modal']:
            self.assertIn(expected, html)
        self.assertIn('id="usage-view-count"', html)
        self.assertIn('id="usage-view-cost"', html)
        self.assertIn('$3.90', html)

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
        cost_report = {
            'currency': 'USD', 'total': '3.90', 'count': 1, 'pending_count': 2,
            'daily_totals': [{'amount': '3.90' if day == 3 else '0.00'} for day in data['days']],
            'rows': [{'user_id': 2, 'username': 'creator01', 'monthly_amount': '3.90',
                      'daily': [{'amount': '3.90' if day == 3 else '0.00'} for day in data['days']]}],
        }
        with patch.object(routes, '_usage_month_data', return_value=data) as read, patch.object(routes, '_cost_month_data', return_value=cost_report) as costs:
            response = client.get(prefix+'/usage/monthly?month=2026-05')
            self.assertEqual(response.status_code, 200)
            read.assert_called_once_with(None, 2026, 5, True)
            for private in ['monthly_real', 'real_total', 'override_count', 'is_override', 'note']:
                self.assertNotIn(private, response.text)
            self.assertEqual(response.json()['cost_report']['total'], '3.90')
            self.assertEqual(response.json()['rows'][0]['daily'][2]['display'], 38)
            export = client.get(prefix+'/usage/monthly/export?month=2026-05')
            self.assertEqual(export.status_code, 200)
            with zipfile.ZipFile(io.BytesIO(export.content)) as archive:
                sheet = archive.read('xl/worksheets/sheet1.xml').decode()
                self.assertNotIn('真实', sheet)
                self.assertNotIn('调整', sheet)
                self.assertIn('每日金额 USD', sheet)
                self.assertIn('3.90', sheet)
            self.assertEqual(costs.call_count, 2)
            for call in costs.call_args_list:
                self.assertEqual(call.args, (None, 2026, 5, None, True))
        self.assertEqual(client.get(prefix+'/costs/day?usage_date=2026-05-03').status_code, 403)
        for endpoint in ['daily-override/form', 'daily-override/delete/form']:
            response = client.post(prefix+'/usage/'+endpoint, data={'user_id':2, 'usage_date':'2026-05-03', 'override_count':77})
            self.assertEqual(response.status_code, 403)

    def test_admin_json_and_export_include_costs(self):
        app = FastAPI()
        app.include_router(routes.router)
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, role='admin')
        app.dependency_overrides[get_db] = lambda: None
        data = build_usage_preview(fixtures.user, '2026-05')
        data['rows'] = [vars(row) for row in data['rows']]
        for row in data['rows']:
            for index, day in enumerate(row['daily'], 1):
                day['day'] = index
        cost_report = {
            'currency': 'USD', 'total': '3.90', 'count': 1, 'pending_count': 2,
            'daily_totals': [{'amount': '3.90' if day == 3 else '0.00'} for day in data['days']],
            'rows': [{'user_id': 2, 'username': 'creator01', 'monthly_amount': '3.90',
                      'daily': [{'amount': '3.90' if day == 3 else '0.00'} for day in data['days']]}],
        }
        client = TestClient(app)
        with patch.object(routes, '_usage_month_data', return_value=data), patch.object(routes, '_cost_month_data', return_value=cost_report):
            response = client.get('/admin/usage/monthly?month=2026-05')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['cost_report']['total'], '3.90')
            export = client.get('/admin/usage/monthly/export?month=2026-05')
            self.assertEqual(export.status_code, 200)
            with zipfile.ZipFile(io.BytesIO(export.content)) as archive:
                sheet = archive.read('xl/worksheets/sheet1.xml').decode()
                self.assertIn('每日金额 USD', sheet)
                self.assertIn('待计费任务', sheet)
                root = ElementTree.fromstring(sheet)
                ns = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
                rows = root.findall('x:sheetData/x:row', ns)
                self.assertIn('创作一组', ElementTree.tostring(rows[3], encoding='unicode'))
                self.assertIn('金额 USD', ElementTree.tostring(rows[4], encoding='unicode'))
                self.assertEqual(rows[4].find("x:c[@r='B5']/x:v", ns).text, '3.90')
                self.assertEqual(rows[4].find("x:c[@r='E5']/x:v", ns).text, '3.90')

    def test_subadmin_costs_exclude_hidden_users_and_pending(self):
        engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        session = sessionmaker(engine)
        created = datetime(2026, 5, 3, 8, 0, tzinfo=UTC)
        with session() as db:
            db.add_all([
                User(id=1, username='visible', password_hash='x', role='user', status='active'),
                User(id=2, username='hidden', password_hash='x', role='user', status='active', hidden_from_subadmin_reports=True),
            ])
            for index, (user_id, state, amount) in enumerate([
                (1, 'settled', Decimal('3.90')),
                (2, 'settled', Decimal('2.00')),
                (1, 'pending', None),
                (2, 'pending', None),
            ], 1):
                db.add(JobCost(id=index, source_job_id=index, source_user_id=user_id,
                               username='visible' if user_id == 1 else 'hidden', provider_key_id=1,
                               api_base_url='https://example.test', provider_name='test', remote_task_id=f'task-{index}',
                               model='video-model', seconds=15, state=state, amount=amount,
                               currency='USD', usage_date=date(2026, 5, 3) if state == 'settled' else None,
                               created_at=created))
            db.commit()
            scoped = routes._cost_month_data(db, 2026, 5, hide_subadmin_hidden=True)
            all_users = routes._cost_month_data(db, 2026, 5)
        self.assertEqual(scoped['total'], '3.90')
        self.assertEqual(scoped['pending_count'], 1)
        self.assertEqual([row['username'] for row in scoped['rows']], ['visible'])
        self.assertEqual(all_users['total'], '5.90')
        self.assertEqual(all_users['pending_count'], 2)


if __name__ == '__main__':
    unittest.main()
