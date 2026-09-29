"""Real local routes and mocked gateway transport; no paid generation."""
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4
import httpx
from fastapi.testclient import TestClient
from test_flow_omni_integration import FlowEnvironment
from app.models.tables import ProviderKey, Job, QuotaWallet, User
from app.services.crypto import encrypt_secret
from app.services import sora_api
from app.services.model_capabilities import capabilities, matches_ratio, validate_grok, GROK_MODELS
from app.services.job_regeneration import regenerate_failed_jobs


class GrokContractTests(unittest.TestCase):
    def test_every_resolution_ratio_and_duration_boundary(self):
        for model in GROK_MODELS:
            cap = capabilities('oaire_grok', model)
            for resolution in cap['resolutions']:
                for ratio in cap['ratios']:
                    for seconds in (1, 6, 15):
                        with self.subTest(model=model, resolution=resolution, ratio=ratio, seconds=seconds):
                            client = MagicMock()
                            client.__enter__.return_value = client
                            client.post.return_value = httpx.Response(200, json={'id':'grok-1', 'status':'queued'})
                            with patch.object(sora_api.httpx, 'Client', return_value=client):
                                sora_api.create_video('secret', 'scene', seconds, '720x1280', model_id=model,
                                    provider_name='oaire_grok', api_base_url='https://gateway.example',
                                    resolution=resolution, aspect_ratio=ratio)
                            self.assertEqual(client.post.call_args.args[0], 'https://gateway.example/v1/videos')
                            self.assertEqual(client.post.call_args.kwargs['json'], {'model':model,'prompt':'scene',
                                'seconds':str(seconds),'resolution':resolution,'aspect_ratio':ratio})

    def test_invalid_options_and_image_count_fail_before_network(self):
        with patch.object(sora_api.httpx, 'Client') as http:
            for change in ({'seconds':0},{'seconds':16},{'resolution':'1080p'}, {'aspect_ratio':'4:3'},
                           {'model_id':'grok-imagine-video-6s'}, {'reference_image_urls':['https://a/1','https://a/2']}):
                args = dict(api_key='secret', prompt='scene', seconds=6, size='720x1280',
                    model_id=GROK_MODELS[0], provider_name='oaire_grok', api_base_url='https://gateway.example',
                    resolution='480p', aspect_ratio='9:16')
                with self.subTest(change=change), self.assertRaises(sora_api.UpstreamError):
                    sora_api.create_video(**{**args, **change})
            http.assert_not_called()

    def test_single_multi_image_fields_and_polling(self):
        client = MagicMock(); client.__enter__.return_value = client
        client.post.return_value = httpx.Response(200,json={'id':'grok-1','status':'queued'})
        client.get.return_value = httpx.Response(200,json={'id':'grok-1','status':'completed','video_url':'https://cdn.example/result.mp4'})
        for count in (1,7):
            images = [f'https://cdn.example/{i}.png' for i in range(count)]
            with patch.object(sora_api.httpx,'Client',return_value=client):
                sora_api.create_video('secret','scene',6,'720x1280',model_id=GROK_MODELS[1],
                    provider_name='oaire_grok',api_base_url='https://gateway.example',resolution='720p',
                    aspect_ratio='9:16',reference_image_urls=images)
            payload=client.post.call_args.kwargs['json']
            self.assertEqual(payload['image'] if count==1 else payload['reference_images'],images[0] if count==1 else images)
            self.assertNotIn('image_url',payload)
        with patch.object(sora_api.httpx,'Client',return_value=client):
            data,_,_=sora_api.fetch_video_status('secret','grok-1','https://gateway.example','oaire_grok')
        self.assertEqual(data['video_url'],'https://cdn.example/result.mp4')
        self.assertEqual(client.get.call_args.args[0],'https://gateway.example/v1/videos/grok-1')

    def test_ratio_compares_proportions_not_pixels(self):
        for dims in [(720,1280),(1080,1920),(480,854)]:
            self.assertTrue(matches_ratio(*dims,'9:16'))
        self.assertFalse(matches_ratio(1280,720,'9:16'))
        self.assertFalse(matches_ratio(0,0,'9:16'))


class GrokCreationTests(unittest.TestCase):
    def setUp(self):
        self.env=FlowEnvironment();self.addCleanup(self.env.close)
        with self.env.Session() as db:
            db.add(ProviderKey(id=5,name='Grok',provider_name='oaire_grok',model_id=GROK_MODELS[1],
                api_base_url='https://gateway.example',key_masked='***',key_encrypted=encrypt_secret('secret')))
            db.commit()
        self.client=TestClient(self.env.app)
        self.assertEqual(self.client.post('/auth/login-browser',json={'username':'creator','password':' old-password '}).status_code,200)

    def payload(self, **changes):
        return dict(prompt='scene',prompts=['scene'],product_name='APP',region_name='CN',model_choice='key:5:model',
                    seconds='7',size='720x1280',resolution='720p',aspect_ratio='1:1',batch_request_id=str(uuid4()),**changes)

    def test_all_creation_routes_persist_selected_specs(self):
        for route in ['/app/jobs','/app/jobs/batch','/app/jobs/form','/app/jobs/batch/form']:
            response=self.client.post(route,data=self.payload(),follow_redirects=False)
            self.assertIn(response.status_code,[200,303],response.text)
        with self.env.Session() as db:
            jobs=db.query(Job).all();self.assertEqual(len(jobs),4)
            for job in jobs:self.assertEqual((job.model,job.seconds,job.resolution,job.aspect_ratio,job.size),(GROK_MODELS[1],7,'720p','1:1','720x720'))
        page=self.client.get('/app').text
        for control in ['job-resolution-select','job-aspect-select','job-seconds-select']:
            self.assertIn(control,page)
        self.assertEqual(page.count('value="key:5:model"'),1)
        self.assertNotIn('grok-imagine-video-6s',page)

    def test_invalid_inputs_do_not_create_or_reserve(self):
        for changes in [{'seconds':'0'},{'seconds':'16'},{'seconds':'1.5'},{'resolution':'4k'}, {'aspect_ratio':'4:3'},
                        {'resolution':'1080p','omni_reference_image_urls':['https://cdn.example/a','https://cdn.example/b']}]:
            data=self.payload();data.update(changes)
            r=self.client.post('/app/jobs/batch',data=data);self.assertEqual(r.status_code,400,r.text)
        with self.env.Session() as db:
            self.assertEqual(db.query(Job).count(),0)
            self.assertEqual(db.query(QuotaWallet).filter_by(user_id=1).one().reserved_quota,0)

    def test_ratio_confirmation_is_scoped_and_cannot_skip_readability(self):
        url='https://cdn.example/image.png';data=self.payload();data['omni_reference_image_urls']=[url]
        with patch('app.api.user.routes.fetch_image_dimensions',return_value=(1080,1920,'image/png',123)):
            self.assertEqual(self.client.post('/app/jobs/batch',data=data).status_code,400)
            data['confirmed_grok_ratios']=['9:16|'+url]
            self.assertEqual(self.client.post('/app/jobs/batch',data=data).status_code,400)
            data['confirmed_grok_ratios']=['1:1|'+url]
            self.assertEqual(self.client.post('/app/jobs/batch',data=data).status_code,200)
        data['batch_request_id']=str(uuid4())
        with patch('app.api.user.routes.fetch_image_dimensions',side_effect=ValueError('无法读取')):
            self.assertEqual(self.client.post('/app/jobs/batch',data=data).status_code,400)

    def test_retry_preserves_specs_and_batch_with_idempotency(self):
        response=self.client.post('/app/jobs/batch',data=self.payload()).json()
        source_id=response['job_ids'][0]
        with self.env.Session() as db:
            original=db.get(Job,source_id);original.status='failed';db.commit()
            first=regenerate_failed_jobs(db,db.get(User,1),original.batch_id,[source_id])[0]
            again=regenerate_failed_jobs(db,db.get(User,1),original.batch_id,[source_id])[0]
            self.assertEqual(first.id,again.id)
            self.assertEqual((first.batch_id,first.resolution,first.aspect_ratio,first.seconds),
                             (original.batch_id,'720p','1:1',7))

    def test_worker_transmits_saved_specs_then_polls_same_task(self):
        from app.services import worker_submitter
        from app.services.worker_poller import poll_remote
        response=self.client.post('/app/jobs/batch',data=self.payload()).json()
        job_id=response['job_ids'][0]
        client=MagicMock();client.__enter__.return_value=client
        client.post.return_value=httpx.Response(200,json={'id':'grok-worker','status':'queued'})
        client.get.return_value=httpx.Response(200,json={'id':'grok-worker','status':'completed','video_url':'https://cdn.example/result.mp4'})
        with patch.object(worker_submitter,'SessionLocal',self.env.Session), \
             patch.object(worker_submitter,'_acquire_job_lock',return_value=True), \
             patch.object(worker_submitter,'_release_job_lock'), \
             patch.object(sora_api.httpx,'Client',return_value=client):
            worker_submitter.submit_queued_job(job_id)
            payload=client.post.call_args.kwargs['json']
            self.assertEqual((payload['seconds'],payload['resolution'],payload['aspect_ratio']),('7','720p','1:1'))
            with self.env.Session() as db:
                job=db.get(Job,job_id)
                self.assertEqual(job.remote_task_id,'grok-worker')
                poll_remote(db,job,db.get(ProviderKey,5),'secret')
                self.assertEqual(job.status,'remote_completed')
                self.assertEqual((job.resolution,job.aspect_ratio,job.seconds),('720p','1:1',7))
        self.assertEqual(client.post.call_count,1)


if __name__=='__main__':unittest.main()
