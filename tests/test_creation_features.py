import tempfile
import unittest
from uuid import uuid4
from pathlib import Path
from urllib.parse import unquote
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.models.tables import ProviderKey, JobBatch, Job, JobFile
from app.services.system_settings import setting_defaults, upsert_system_setting
from app.core.config import settings
from creation_features_support import CreationFeaturesEnvironment


class CreationFeatureTests(unittest.TestCase):
    def setUp(self):
        self.env=CreationFeaturesEnvironment();self.addCleanup(self.env.close)
        self.client=TestClient(self.env.app)
        self.login('admin')

    def login(self,name):
        self.assertEqual(self.client.post('/auth/login-browser',json={'username':name,'password':' old-password '}).status_code,200)

    def test_admin_default_is_used_and_disabled_channel_falls_back(self):
        values={**setting_defaults(),'default_model_choice':'key:1:10'}
        response=self.client.post('/admin/settings/update/form',data=values,headers={'Origin':'http://testserver'},follow_redirects=False)
        self.assertEqual(response.status_code,303)
        self.login('creator')
        page=self.client.get('/app');self.assertEqual(page.status_code,200)
        self.assertIn('value="key:1:10" selected data-seconds="10"',page.text)
        self.assertIn('&lt;script&gt;测试&lt;/script&gt;',page.text)
        with self.env.Session() as db:
            db.get(ProviderKey,1).status='disabled';db.commit()
        self.assertNotIn('value="key:1:10"',self.client.get('/app').text)
        self.login('admin')
        self.assertIn('原默认模型已不可用',self.client.get('/admin/settings/page').text)

    def test_invalid_or_deleted_default_rejected_atomically(self):
        for value in ('key:999:10','key:1:8','garbage'):
            response=self.client.post('/admin/settings/update/form',data={**setting_defaults(),'default_model_choice':value},headers={'Origin':'http://testserver'})
            self.assertEqual(response.status_code,400)
        with self.env.Session() as db:
            db.get(ProviderKey,1).status='deleted';db.commit()
            with self.assertRaises(ValueError):upsert_system_setting(db,'default_model_choice','key:1:10')

    def test_zip_name_contains_app_region_and_batch_id(self):
        self.login('creator')
        with tempfile.TemporaryDirectory() as folder, patch.object(settings,'files_temp_dir',Path(folder)):
            video=Path(folder)/'video.mp4';video.write_bytes(b'test-video')
            with self.env.Session() as db:
                db.add(JobBatch(id=7,user_id=1,request_id=uuid4(),batch_code='BTEST7',product_name='Nice/Reels',region_name='巴西',batch_name='自动生成的冗长批次名字'))
                db.add(Job(id=1,user_id=1,batch_id=7,prompt='test',status='completed'))
                db.flush()
                db.add(JobFile(id=1,job_id=1,file_type='output_video',file_path=str(video),file_name='video.mp4',playable=True));db.commit()
            response=self.client.get('/app/job-batches/7/download-zip')
            self.assertEqual(response.status_code,200)
            self.assertIn('Nice-Reels-巴西-批次-7.zip',unquote(response.headers['content-disposition']))
            self.assertTrue(response.content.startswith(b'PK'))
            self.login('other')
            self.assertEqual(self.client.get('/app/job-batches/7/download-zip').status_code,404)

if __name__=='__main__':unittest.main()
