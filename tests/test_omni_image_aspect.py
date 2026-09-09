import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from app.api.user import routes
from app.api.admin import routes as admin
from app.deps import get_current_user, get_db
from app.models.tables import ReferenceImagePreset

URL='https://example.test/square.png'
USER=SimpleNamespace(id=2,role='user')

class OmniImageAspectTests(unittest.TestCase):
    def test_omni_accepts_arbitrary_image_dimensions_for_both_output_orientations(self):
        for provider in ['veo_omni','wuyin_omni']:
            for size in ['720x1280','1280x720']:
                for dimensions in [(512,512),(1920,1080),(600,1000)]:
                    with self.subTest(provider=provider,size=size,dimensions=dimensions),patch.object(routes,'fetch_image_dimensions',return_value=(*dimensions,'image/png',100)):
                        images,_=routes._resolve_job_reference_materials(None,USER,provider,size,omni_reference_image_urls=[URL])
                        self.assertEqual(images[0][2:],dimensions)

    def test_omni_preset_and_legacy_url_fields_accept_square_images(self):
        db=MagicMock();db.query.return_value.filter.return_value.first.return_value=SimpleNamespace(image_url=URL,name='Square',width=512,height=512)
        for provider in ['veo_omni','wuyin_omni']:
            images,_=routes._resolve_job_reference_materials(db,USER,provider,'720x1280',reference_preset_id='9')
            self.assertEqual(images[0],(URL,'Square',512,512))
            with patch.object(routes,'fetch_image_dimensions',return_value=(512,512,None,100)):
                images,_=routes._resolve_job_reference_materials(None,USER,provider,'720x1280',reference_image_url=URL)
                self.assertEqual(images[0][2:],(512,512))

    def test_non_omni_still_requires_matching_size(self):
        with patch.object(routes,'fetch_image_dimensions',return_value=(512,512,None,100)):
            with self.assertRaisesRegex(HTTPException,'参考图尺寸不匹配'):
                routes._resolve_job_reference_materials(None,USER,'sora_api','720x1280',reference_image_url=URL)

    def test_presets_store_arbitrary_positive_dimensions(self):
        row=ReferenceImagePreset()
        with patch.object(routes,'fetch_image_dimensions',return_value=(512,512,None,100)):
            routes._apply_reference_preset_values(row,'Square',URL,'100')
        self.assertEqual((row.width,row.height,row.aspect_ratio),(512,512,'1:1'))
        admin._ensure_reference_dimensions(512,512)
        for check in [routes._ensure_reference_dimensions,admin._ensure_reference_dimensions]:
            with self.assertRaises(HTTPException):check(0,512)

    def test_all_generation_endpoints_accept_square_omni_without_confirmation(self):
        app=FastAPI();app.include_router(routes.router)
        app.dependency_overrides[get_current_user]=lambda:USER
        app.dependency_overrides[get_db]=lambda:None
        client=TestClient(app)
        batch=SimpleNamespace(id=12,batch_code='B12',batch_name='test',product_name='APP',region_name='CN')
        job=SimpleNamespace(id=101,product_name='APP',region_name='CN',remote_task_id=None,status='queued')
        for provider in ['veo_omni','wuyin_omni']:
            with ExitStack() as stack:
                for name,value in [('_parse_model_choice',(provider,10,1)),('_assert_requested_key_available',None),('_risk_failure_map',{}),('_select_model_provider_key',SimpleNamespace(provider_name=provider)),('model_id_for_seconds','omni-model'),('queue_text','queued')]:
                    stack.enter_context(patch.object(routes,name,return_value=value))
                create=stack.enter_context(patch.object(routes,'create_jobs_batch_and_reserve',return_value=(batch,[job])))
                stack.enter_context(patch.object(routes,'fetch_image_dimensions',return_value=(512,512,'image/png',100)))
                for suffix in ['/jobs','/jobs/batch','/jobs/form','/jobs/batch/form']:
                    with self.subTest(provider=provider,suffix=suffix):
                        response=client.post(routes.router.prefix+suffix,data={'prompt':'test','prompts':'test','product_name':'APP','region_name':'CN','seconds':'10','size':'720x1280','model_choice':'key:1:10','omni_reference_image_urls':URL},follow_redirects=False)
                        self.assertIn(response.status_code,[200,303],response.text)
                        self.assertEqual(create.call_args.kwargs['reference_images'][0][2:],(512,512))

if __name__=='__main__':unittest.main()
