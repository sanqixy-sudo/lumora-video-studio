import unittest
from unittest.mock import patch
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request
from app.core.config import settings
from app.core.request_security import require_same_origin
from app.services.system_settings import setting_defaults
from creation_features_support import CreationFeaturesEnvironment


class ReverseProxyOriginTests(unittest.TestCase):
    def check(self, source, *, host='video.example.com', extra=None, public='https://video.example.com'):
        headers={'host':host,**source,**(extra or {})}
        request=Request({'type':'http','method':'POST','scheme':'http','path':'/admin/settings/update/form',
                         'root_path':'','query_string':b'','server':('127.0.0.1',8000),
                         'headers':[(k.encode(),v.encode()) for k,v in headers.items()]})
        with patch.object(settings,'public_origin',public):
            require_same_origin(request)

    def test_configured_https_origin_and_referer_allow_proxy(self):
        self.check({'origin':'https://video.example.com'})
        self.check({'referer':'https://video.example.com/admin/settings/page'})
        self.check({'origin':'http://192.168.88.33:8088'},host='192.168.88.33:8088')
        self.check({'origin':'https://video.example.com:8443'},host='video.example.com:8443',public='https://video.example.com:8443')

    def test_invalid_sources_hosts_and_untrusted_forwarding_rejected(self):
        cases=[({},{}),({'origin':'null'},{}),({'origin':'https://evil.example'},{}),
               ({'origin':'https://video.example.com:8443'},{}),
               ({'origin':'https://video.example.com.evil'},{}),
               ({'origin':'https://video.example.com'},{'host':'192.168.88.33:8088'}),
               ({'origin':'https://video.example.com'},{'extra':{'sec-fetch-site':'cross-site'}}),
               ({'origin':'https://video.example.com'},{'public':''}),
               ({'origin':'https://evil.example'},{'extra':{'x-forwarded-host':'evil.example','x-forwarded-proto':'https'}})]
        for source,options in cases:
            with self.subTest(source=source,options=options),self.assertRaises(HTTPException) as caught:
                self.check(source,**options)
            self.assertEqual(caught.exception.status_code,403)

    def test_default_model_save_through_tls_proxy_and_role_check(self):
        env=CreationFeaturesEnvironment();self.addCleanup(env.close)
        client=TestClient(env.app,base_url='http://video.example.com')
        self.assertEqual(client.post('/auth/login-browser',json={'username':'admin','password':' old-password '}).status_code,200)
        values={**setting_defaults(),'default_model_choice':'key:1:10'}
        headers={'Origin':'https://video.example.com','Accept':'application/json'}
        with patch.object(settings,'public_origin','https://video.example.com'):
            response=client.post('/admin/settings/update/form',data=values,headers=headers,follow_redirects=False)
            self.assertEqual(response.status_code,303,response.text)
            client.post('/auth/login-browser',json={'username':'creator','password':' old-password '})
            self.assertIn('value="key:1:10" selected',client.get('/app').text)
            self.assertEqual(client.post('/admin/settings/update/form',data=values,headers=headers).status_code,403)
            headers['Origin']='https://evil.example'
            rejected=client.post('/app/settings/profile/form',data={'display_name':'test'},headers=headers)
            self.assertEqual(rejected.status_code,403)
            self.assertIn('请求来源无效',rejected.json()['detail'])

if __name__=='__main__':unittest.main()
