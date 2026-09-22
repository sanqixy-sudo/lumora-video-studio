import unittest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.models.tables import Job,JobBatch,JobFile,JobEvent,QuotaWallet,JobQuotaReservation,QuotaLedger,ProviderKey,RiskControlRule,User
from regeneration_support import RegenerationEnvironment

class BatchRegenerationTests(unittest.TestCase):
    def setUp(self):
        self.env=RegenerationEnvironment();self.addCleanup(self.env.close)
        self.client=TestClient(self.env.app)
        self.login('creator')
    def login(self,name):
        self.assertEqual(self.client.post('/auth/login-browser',json={'username':name,'password':' old-password '}).status_code,200)
    def retry(self,ids,**kw):
        return self.client.post('/app/job-batches/10/regenerate',json={'job_ids':ids},headers=kw.get('headers',{'Origin':'http://testserver'}))
    def test_batch_list_exposes_eligible_retry_and_hides_after_requeue(self):
        response=self.client.get('/app/job-batches/page')
        self.assertEqual(response.status_code,200)
        self.assertIn('data-batch-regenerate="10"',response.text)
        self.assertIn('重试失败 2 项',response.text)
        self.assertEqual(self.retry([1,2]).status_code,200)
        self.assertNotIn('data-batch-regenerate="10"',self.client.get('/app/job-batches/page').text)
        self.login('other')
        self.assertNotIn('data-batch-regenerate="10"',self.client.get('/app/job-batches/page').text)
    def test_batch_list_hides_retry_for_disabled_channel(self):
        with self.env.Session() as db:
            db.get(ProviderKey,1).status='disabled';db.commit()
        self.assertNotIn('data-batch-regenerate="10"',self.client.get('/app/job-batches/page').text)
    def test_same_batch_same_positions_preserve_old_attempts_and_copy_materials(self):
        quote=self.client.get('/app/job-batches/10/regeneration-preview').json()
        self.assertEqual(quote['job_ids'],[1,2]);self.assertEqual(quote['quota'],2)
        response=self.retry(quote['job_ids']);self.assertEqual(response.status_code,200,response.text)
        ids=response.json()['job_ids']
        self.assertEqual(self.client.post('/app/jobs/2/resume').status_code,400)
        with self.env.Session() as db:
            self.assertEqual(db.query(JobBatch).count(),1)
            for original_id,new_id in zip([1,2],ids):
                old,new=db.get(Job,original_id),db.get(Job,new_id)
                self.assertEqual(old.status,'failed');self.assertEqual(new.status,'queued')
                self.assertEqual((new.batch_id,new.batch_index),(10,original_id))
                self.assertEqual(new.prompt,old.prompt);self.assertNotEqual(new.request_id,old.request_id)
                self.assertIsNone(new.remote_task_id)
            ref=db.query(JobFile).filter(JobFile.job_id==ids[0]).one();self.assertEqual(ref.file_name,'参考图')
            self.assertEqual(db.query(QuotaLedger).count(),2)
            self.assertEqual(db.query(JobQuotaReservation).filter_by(job_id=2).one().status,'refunded')
            self.assertEqual(db.query(QuotaWallet).filter_by(user_id=1).one().reserved_quota,2)
        payload=self.client.get('/app/job-batches/10').json()
        self.assertEqual(len(payload['jobs']),4)
        self.assertEqual(payload['batch']['total_count'],4)
        self.assertEqual(payload['batch']['active_count'],2)
        self.assertNotIn(1,[j['id'] for j in payload['jobs']])
        html=self.client.get('/app/job-batches/10/result').text
        self.assertIn('上次失败记录',html)
        self.assertEqual(html.count('data-batch-job='),4)
    def test_replayed_clicks_do_not_add_tasks_or_reserve_twice(self):
        first=self.retry([1,2]).json();second=self.retry([2,1,1]).json()
        self.assertEqual(set(first['job_ids']),set(second['job_ids']))
        with self.env.Session() as db:
            self.assertEqual(db.query(Job).count(),6)
            self.assertEqual(db.query(QuotaWallet).filter_by(user_id=1).one().reserved_quota,2)
            child=db.get(Job,first['job_ids'][0]);child.status='failed';db.commit()
        # Replaying the old request still returns that child, not a third attempt.
        self.assertEqual(self.retry([1]).json()['job_ids'],[first['job_ids'][0]])
        self.assertEqual(self.retry([first['job_ids'][0]]).status_code,200)
    def test_insufficient_quota_rolls_back_whole_batch(self):
        with self.env.Session() as db:
            db.query(QuotaWallet).filter_by(user_id=1).one().remaining_quota=1;db.commit()
        self.assertEqual(self.retry([1,2]).status_code,400)
        with self.env.Session() as db:
            self.assertEqual(db.query(Job).count(),4)
            self.assertEqual(db.query(JobEvent).count(),0)
            self.assertEqual(db.query(QuotaWallet).filter_by(user_id=1).one().reserved_quota,0)
    def test_states_and_ownership_and_source_checks(self):
        for ids in ([3],[4],[1,4],[999]):
            self.assertIn(self.retry(ids).status_code,[400,404])
        self.assertEqual(self.retry([1],headers={'Origin':'https://evil.example'}).status_code,403)
        self.login('other');self.assertEqual(self.retry([1]).status_code,404)
        self.assertEqual(self.client.get('/app/job-batches/10/regeneration-preview').status_code,404)
    def test_channel_model_risk_and_missing_material_checks(self):
        with self.env.Session() as db:
            provider=db.get(ProviderKey,1);provider.status='disabled';db.commit()
        self.assertEqual(self.retry([1]).status_code,400)
        with self.env.Session() as db:
            provider=db.get(ProviderKey,1);provider.status='active';provider.model_id_10s='changed';db.commit()
        self.assertEqual(self.retry([1]).status_code,400)
        with self.env.Session() as db:
            db.get(ProviderKey,1).model_id_10s='veo-omni-flash'
            db.add(RiskControlRule(keywords=['原提示词'],error_message='拒绝'));db.commit()
        self.assertEqual(self.retry([1]).status_code,400)
        with self.env.Session() as db:
            db.query(RiskControlRule).delete();db.add(JobFile(job_id=1,file_type='reference_image',file_path='/missing-original.png',file_name='missing'));db.commit()
        self.assertEqual(self.retry([1]).status_code,400)
    def test_redownload_does_not_regenerate_or_reserve(self):
        path='/app/job-batches/10/jobs/3/retry-download'
        for _ in range(2):self.assertEqual(self.client.post(path,headers={'Origin':'http://testserver'}).status_code,200)
        with self.env.Session() as db:
            self.assertEqual(db.get(Job,3).status,'remote_completed');self.assertEqual(db.get(Job,3).remote_task_id,'old-3')
            self.assertEqual(db.query(Job).count(),4);self.assertEqual(db.query(QuotaWallet).filter_by(user_id=1).one().reserved_quota,0)
            self.assertEqual(db.query(JobEvent).count(),1)
    def test_daily_limit_is_enforced(self):
        with self.env.Session() as db:db.get(User,1).daily_job_limit=4;db.commit()
        self.assertEqual(self.retry([1]).status_code,400)
    def test_database_enforces_single_retry_per_source(self):
        self.retry([1])
        with self.env.Session() as db:
            db.add(Job(user_id=1,batch_id=10,prompt='duplicate',retry_of_job_id=1))
            with self.assertRaises(IntegrityError):db.commit()

if __name__=='__main__':unittest.main()
