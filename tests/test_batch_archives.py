import io,tempfile,unittest,zipfile
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.core.config import settings
from app.models.tables import Job,JobBatch,JobFile
from app.services.batch_archives import _build_slot
from creation_features_support import CreationFeaturesEnvironment

class BatchArchiveEnvironment(CreationFeaturesEnvironment):
    def __init__(self):
        super().__init__()
        self.directory=tempfile.TemporaryDirectory()
        self.root=Path(self.directory.name)
        self.original_temp=settings.files_temp_dir
        self.temp_patch=patch.object(settings,'files_temp_dir',self.root/'temp');self.temp_patch.start()
        self.patches.append(self.temp_patch)
        with self.Session() as db:
            for i,owner in [(10,1),(11,1),(12,2),(13,1)]:
                db.add(JobBatch(id=i,user_id=owner,request_id=uuid4(),batch_code='ZIP'+str(i),batch_name='测试批次'+str(i),product_name='Drama/Play',region_name='巴西',total_count=2 if i==10 else 1))
            for i,batch,owner,status in [(1,10,1,'completed'),(2,10,1,'failed'),(3,11,1,'completed'),(4,12,2,'completed'),(5,10,1,'completed')]:
                path=self.root/f'{i}.mp4';path.write_bytes(f'video-{i}'.encode())
                db.add(Job(id=i,user_id=owner,batch_id=batch,batch_index=i,model='veo-omni-flash',prompt='test',product_name='Drama/Play',region_name='巴西',status=status,retry_of_job_id=2 if i==5 else None))
                db.flush();db.add(JobFile(id=i,job_id=i,file_type='output_video',file_path=str(path),file_name=path.name,playable=True))
            db.commit()
    def close(self):
        super().close();self.directory.cleanup()

class BatchArchiveTests(unittest.TestCase):
    def setUp(self):
        self.env=BatchArchiveEnvironment();self.addCleanup(self.env.close)
        self.client=TestClient(self.env.app)
        self.client.post('/auth/login-browser',json={'username':'creator','password':' old-password '})
    def download(self,ids):
        return self.client.get('/app/job-batches/bulk-download',params={'batch_ids':ids,'download_token':'a'*32})
    def test_outer_zip_contains_named_batch_zips_with_latest_videos(self):
        response=self.download('10,11,10');self.assertEqual(response.status_code,200,response.text[:100] if response.status_code!=200 else '')
        self.assertEqual(response.cookies['batch_zip_'+'a'*32],'ready')
        with zipfile.ZipFile(io.BytesIO(response.content)) as outer:
            self.assertEqual(outer.namelist(),['Drama-Play-巴西-批次-10.zip','Drama-Play-巴西-批次-11.zip'])
            self.assertIsNone(outer.testzip())
            expected=[{b'video-1',b'video-5'},{b'video-3'}]
            for name,contents in zip(outer.namelist(),expected):
                with zipfile.ZipFile(io.BytesIO(outer.read(name))) as inner:
                    self.assertEqual({inner.read(n) for n in inner.namelist()},contents)
                    self.assertTrue(all('/' not in n and '\\' not in n for n in inner.namelist()))
                    self.assertIsNone(inner.testzip())
        self.assertEqual(list(settings.files_temp_dir.iterdir()),[])
    def test_ownership_and_invalid_selection_fail_without_partial_zip(self):
        for ids in ('10,12','999','13','10,13','', '0','-1','1;2',','.join(str(i) for i in range(1,22)),'999999999999999999999'):
            with self.subTest(ids=ids):
                response=self.download(ids);self.assertIn(response.status_code,[400,404])
                self.assertEqual(response.cookies['batch_zip_'+'a'*32],'error')
        self.assertFalse(settings.files_temp_dir.exists() and list(settings.files_temp_dir.iterdir()))
    def test_missing_file_and_busy_and_space_errors_are_explicit(self):
        (self.env.root/'3.mp4').unlink()
        self.assertEqual(self.download('11').status_code,400)
        with patch('app.services.batch_archives.shutil.disk_usage') as usage:
            usage.return_value.free=0
            self.assertEqual(self.download('10').status_code,507)
        _build_slot.acquire()
        try:self.assertEqual(self.download('10').status_code,429)
        finally:_build_slot.release()
    def test_mid_build_failure_cleans_temp_file(self):
        with patch('zipfile.ZipFile.write',side_effect=OSError('disk full')):
            self.assertEqual(self.download('10').status_code,503)
        self.assertEqual(list(settings.files_temp_dir.iterdir()),[])
    def test_ui_has_selection_and_disables_empty_batches(self):
        page=self.client.get('/app/job-batches/page');self.assertEqual(page.status_code,200)
        self.assertIn('batch-bulk-download',page.text)
        self.assertIn('总 ZIP 内每个批次一个 ZIP',page.text)
        self.assertIn('暂无可下载视频',page.text)
        self.assertNotIn('ZIP12',page.text)

if __name__=='__main__':unittest.main()
