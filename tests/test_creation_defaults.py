import html
import json
import re
import unittest

from fastapi.testclient import TestClient
from test_flow_omni_integration import FlowEnvironment
from app.models.tables import AppSetting, ProviderKey
from app.services.crypto import encrypt_secret
from app.services.system_settings import get_creation_defaults, setting_defaults, upsert_system_setting


class CreationDefaultsTests(unittest.TestCase):
    def setUp(self):
        self.env = FlowEnvironment()
        self.addCleanup(self.env.close)
        self.client = TestClient(self.env.app)
        self.addCleanup(self.client.close)
        with self.env.Session() as db:
            for id_, model in [(5, 'grok-imagine-video'), (6, 'grok-imagine-video-1.5-preview')]:
                db.add(ProviderKey(id=id_, name='Grok', provider_name='oaire_grok', model_id=model,
                    api_base_url='https://gateway.example', key_masked='***', key_encrypted=encrypt_secret('fixture')))
            db.add(ProviderKey(id=7, name='Omni', provider_name='oaire_omni', model_id_10s='omni-fast-no-water',
                api_base_url='https://gateway.example', key_masked='***', key_encrypted=encrypt_secret('fixture')))
            db.commit()
        self.login('admin')

    def login(self, username):
        self.assertEqual(self.client.post('/auth/login-browser', json={
            'username': username, 'password': ' old-password '}).status_code, 200)

    def save(self, **changes):
        return self.client.post('/admin/settings/update/form', data={**setting_defaults(), **changes},
            headers={'Origin': 'http://testserver'}, follow_redirects=False)

    def defaults(self):
        with self.env.Session() as db:
            return get_creation_defaults(db)

    def test_saved_specs_are_rendered_for_admin_and_new_creation(self):
        expected = dict(default_model_choice='key:6:model', default_resolution='1080p',
                        default_aspect_ratio='1:1', default_seconds='12')
        self.assertEqual(self.save(**expected).status_code, 303)
        self.assertEqual(self.defaults(), expected)
        with self.env.Session() as db:
            for key, value in expected.items():
                self.assertEqual(db.query(AppSetting).filter_by(key=key).one().value, value)
        page = self.client.get('/admin/settings/page')
        self.assertEqual(page.status_code, 200)
        for key, value in expected.items():
            select = re.search(r'<select[^>]*id="setting-' + key + r'"[^>]*>(.*?)</select>', page.text, re.S)
            self.assertIsNotNone(select)
            self.assertRegex(select[1], r'<option value="' + re.escape(value) + r'"[^>]*selected')
        self.login('creator')
        page = self.client.get('/app')
        self.assertEqual(page.status_code, 200)
        embedded = re.search(r"data-generation-defaults='([^']+)'", page.text)[1]
        self.assertEqual(json.loads(html.unescape(embedded)), expected)

    def test_invalid_specs_do_not_save_any_setting(self):
        valid = dict(default_model_choice='key:6:model', default_resolution='720p',
                     default_aspect_ratio='16:9', default_seconds='9')
        self.assertEqual(self.save(**valid).status_code, 303)
        with self.env.Session() as db:
            before = {row.key: row.value for row in db.query(AppSetting).all()}
        for change in [dict(default_model_choice='key:5:model', default_resolution='1080p'),
                       dict(default_seconds='0'), dict(default_seconds='16'), dict(default_seconds='2.5'),
                       dict(default_aspect_ratio='4:3'), dict(default_resolution='4k'),
                       dict(default_model_choice='key:7:10', default_seconds='12')]:
            with self.subTest(change=change):
                response = self.save(**{**valid, **change, 'max_running_jobs': '77'})
                self.assertEqual(response.status_code, 400)
                with self.env.Session() as db:
                    self.assertEqual({row.key: row.value for row in db.query(AppSetting).all()}, before)

    def test_legacy_setting_without_specs_uses_model_defaults(self):
        with self.env.Session() as db:
            upsert_system_setting(db, 'default_model_choice', 'key:7:10')
            db.commit()
        self.assertEqual(self.defaults(), dict(default_model_choice='key:7:10', default_resolution='720p',
                                              default_aspect_ratio='9:16', default_seconds='10'))
        values = {key: value for key, value in setting_defaults().items()
                  if key not in ('default_resolution', 'default_aspect_ratio', 'default_seconds')}
        values['default_model_choice'] = 'key:6:model'
        response = self.client.post('/admin/settings/update/form', data=values,
            headers={'Origin': 'http://testserver'}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.defaults()['default_seconds'], '6')
        self.assertEqual(self.defaults()['default_resolution'], '480p')

    def test_unavailable_and_changed_model_capabilities_fall_back(self):
        self.assertEqual(self.save(default_model_choice='key:6:model', default_resolution='1080p',
                                  default_aspect_ratio='1:1', default_seconds='15').status_code, 303)
        with self.env.Session() as db:
            db.get(ProviderKey, 6).model_id = 'grok-imagine-video'
            db.commit()
        self.assertEqual(self.defaults()['default_resolution'], '480p')
        self.assertEqual(self.defaults()['default_seconds'], '15')
        with self.env.Session() as db:
            db.get(ProviderKey, 6).status = 'disabled'
            db.commit()
        self.assertTrue(all(value == '' for value in self.defaults().values()))
        page = self.client.get('/admin/settings/page').text
        self.assertIn('原默认模型已不可用', page)
        for key in ('default_resolution', 'default_aspect_ratio', 'default_seconds'):
            self.assertRegex(page, r'<select[^>]*id="setting-' + key + r'"[^>]*disabled')

    def test_clear_model_clears_specs(self):
        self.assertEqual(self.save(default_model_choice='key:6:model', default_resolution='1080p',
                                  default_seconds='12').status_code, 303)
        self.assertEqual(self.save(default_model_choice='').status_code, 303)
        self.assertTrue(all(value == '' for value in self.defaults().values()))
        with self.env.Session() as db:
            for key in ('default_resolution', 'default_aspect_ratio', 'default_seconds'):
                self.assertIsNone(db.query(AppSetting).filter_by(key=key).one().value)


if __name__ == '__main__':
    unittest.main()
