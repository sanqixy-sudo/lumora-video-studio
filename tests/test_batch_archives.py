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
    def download(self,batch_id,token='a'*32):
        return self.client.get(f'/app/job-batches/{batch_id}/download-zip',params={'download_token':token})
    def test_separate_zips_contain_latest_videos_and_named_attachments(self):
        from urllib.parse import unquote
        for batch_id,contents in [(10,{b'video-1',b'video-5'}),(11,{b'video-3'})]:
            response=self.download(batch_id)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.cookies['batch_zip_'+'a'*32],'ready')
            self.assertIn(f'Drama-Play-巴西-批次-{batch_id}.zip',unquote(response.headers['content-disposition']))
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                self.assertEqual({archive.read(n) for n in archive.namelist()},contents)
                self.assertTrue(all(n.endswith('.mp4') and '/' not in n for n in archive.namelist()))
                self.assertIsNone(archive.testzip())
            self.assertEqual(list(settings.files_temp_dir.iterdir()),[])
    def test_ownership_and_empty_batch_fail_with_error_cookie(self):
        for batch_id in (12,999,13,0):
            response=self.download(batch_id);self.assertIn(response.status_code,[400,404])
            self.assertEqual(response.cookies['batch_zip_'+'a'*32],'error')
        self.assertEqual(self.download(10,token='invalid').status_code,422)
        self.assertFalse(settings.files_temp_dir.exists() and list(settings.files_temp_dir.iterdir()))
    def test_single_download_without_token_remains_compatible(self):
        self.assertEqual(self.client.get('/app/job-batches/10/download-zip').status_code,200)
        self.assertEqual(self.client.get('/app/job-batches/12/download-zip').status_code,404)
        self.client.cookies.clear()
        self.assertIn(self.download(10).status_code,[401,403])
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
        self.assertIn('依次下载各批次的 ZIP',page.text)
        self.assertIn('暂无可下载视频',page.text)
        self.assertNotIn('ZIP12',page.text)

if __name__=='__main__':unittest.main()
