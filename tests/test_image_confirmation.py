import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from app.api.user import routes
from app.deps import get_current_user, get_db
from app.services.reference_images import fetch_image_dimensions

URL='https://example.test/image.png'
USER=SimpleNamespace(id=2,role='user')


class ImageConfirmationTests(unittest.TestCase):
    def resolve(self, **kw):
        return routes._resolve_job_reference_materials(None,USER,'veo_omni','720x1280',omni_reference_image_urls=[URL],**kw)

    def test_explicit_matching_url_skips_fetch_without_fabricating_dimensions(self):
        with patch.object(routes,'fetch_image_dimensions',side_effect=ValueError('unreadable')) as fetch:
            images,video=self.resolve(confirmed_reference_image_urls=[URL])
            self.assertEqual(images,[(URL,'图片链接参考图',None,None)])
            self.assertIsNone(video)
            fetch.assert_not_called()

    def test_default_and_other_url_confirmation_still_validate(self):
        for confirmations in [None,['https://example.test/other.png']]:
            with self.subTest(confirmations=confirmations),patch.object(routes,'fetch_image_dimensions',side_effect=ValueError('unreadable')):
                with self.assertRaises(HTTPException):self.resolve(confirmed_reference_image_urls=confirmations)
        with patch.object(routes,'fetch_image_dimensions',return_value=(100,100,'image/png',100)):
            images,_=self.resolve()
            self.assertEqual(images[0][2:],(100,100))

    def test_confirmation_does_not_bypass_format_count_or_retired_video(self):
        for kw in [dict(omni_reference_image_urls=['javascript:alert(1)']),dict(omni_reference_image_urls=[URL]*7),dict(omni_reference_video_url='https://example.test/video.mp4')]:
            args={'omni_reference_image_urls':[URL], 'confirmed_reference_image_urls':[URL],**kw}
            with self.subTest(kw=kw),self.assertRaises((ValueError,HTTPException)):
                routes._resolve_job_reference_materials(None,USER,'veo_omni','720x1280',**args)

    def test_preset_permissions_are_never_bypassed(self):
        db=MagicMock();db.query.return_value.filter.return_value.first.return_value=None
        with self.assertRaises(HTTPException):
            routes._resolve_job_reference_materials(db,USER,'veo_omni','720x1280',omni_reference_preset_ids=['9'],confirmed_reference_image_urls=[URL])

    def test_all_four_http_generation_endpoints_forward_confirmations(self):
        app=FastAPI();app.include_router(routes.router)
        app.dependency_overrides[get_current_user]=lambda:USER
        app.dependency_overrides[get_db]=lambda:None
        client=TestClient(app)
        key=SimpleNamespace(provider_name='veo_omni')
        batch=SimpleNamespace(id=12,batch_code='B12',batch_name='test',product_name='APP',region_name='CN')
        job=SimpleNamespace(id=101,product_name='APP',region_name='CN',remote_task_id=None,status='queued')
        with ExitStack() as stack:
            for name,value in [('_parse_model_choice',('veo_omni',10,1)),('_assert_requested_key_available',None),('_risk_failure_map',{}),('_select_model_provider_key',key),('model_id_for_seconds','veo-model'),('queue_text','queued')]:
                stack.enter_context(patch.object(routes,name,return_value=value))
            create=stack.enter_context(patch.object(routes,'create_jobs_batch_and_reserve',return_value=(batch,[job])))
            fetch=stack.enter_context(patch.object(routes,'fetch_image_dimensions',side_effect=ValueError('unreadable')))
            for suffix in ['/jobs','/jobs/batch','/jobs/form','/jobs/batch/form']:
                with self.subTest(suffix=suffix):
                    payload={'prompt':'test','prompts':'test','product_name':'APP','region_name':'CN','seconds':'10','size':'720x1280','model_choice':'key:1:10','omni_reference_image_urls':URL,'confirmed_reference_image_urls':URL}
                    response=client.post(routes.router.prefix+suffix,data=payload,follow_redirects=False)
                    self.assertIn(response.status_code,[200,303],response.text)
                    self.assertEqual(create.call_args.kwargs['reference_images'],[(URL,'图片链接参考图',None,None)])
            fetch.assert_not_called()

    def test_network_failure_explains_actual_failure_category(self):
        original=httpx.Client
        for handler,expected in [(lambda req:httpx.Response(403,request=req),'HTTP 403'),(lambda req:(_ for _ in ()).throw(httpx.ReadTimeout('timeout',request=req)),'超时')]:
            with self.subTest(expected=expected),patch('app.services.reference_images.httpx.Client',side_effect=lambda **kw:original(transport=httpx.MockTransport(handler),**kw)):
                with self.assertRaisesRegex(ValueError,expected):fetch_image_dimensions(URL)


if __name__=='__main__':unittest.main()
