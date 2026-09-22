import json
import tempfile
import unittest
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
from fastapi.testclient import TestClient
from system_settings_support import SystemSettingsEnvironment
from account_settings_support import OLD_PASSWORD
from app.models.tables import AppSetting, AuditLog, ProviderKey
from app.services.system_settings import setting_defaults, upsert_system_setting
from app.services.network_settings import get_proxy_url, proxy_options, validate_proxy_url
from app.services import sora_api, worker_engine


class SystemNetworkSettingsTests(unittest.TestCase):
    def setUp(self):
        self.env = SystemSettingsEnvironment()
        self.addCleanup(self.env.close)
        self.client = TestClient(self.env.app)
        self.login("admin")

    def login(self, username):
        self.assertEqual(self.client.post("/auth/login-browser", json={"username":username,"password":OLD_PASSWORD}).status_code,200)

    def save(self, **changes):
        values=setting_defaults()
        values.update(changes)
        return self.client.post("/admin/settings/update/form",data=values,headers={"Origin":"http://testserver"},follow_redirects=False)

    def test_socks_transports_are_available(self):
        for scheme in ("socks5", "socks5h"):
            with httpx.Client(**sora_api._proxy_client_options(f"{scheme}://127.0.0.1:20170")):
                pass

    def test_proxy_modes_are_independent_and_direct_overrides_environment(self):
        self.assertEqual(self.save(request_proxy_enabled="1",request_proxy_url="http://127.0.0.1:20171",download_proxy_enabled="0",video_download_concurrency="12").status_code,303)
        with self.env.Session() as db, patch.object(sora_api.settings,"video_download_proxy","http://deployment:20171"):
            self.assertEqual(proxy_options(db),{"request_proxy":"http://127.0.0.1:20171","download_proxy":""})
            self.assertEqual(db.get(AppSetting,"video_download_concurrency").value,"12")
        page=self.client.get("/admin/settings/page?notice=settings_saved")
        self.assertEqual(page.status_code,200)
        self.assertIn("设置已保存",page.text)
        self.assertIn("通道生成并发",page.text)

    def test_credentials_are_encrypted_and_never_echoed_or_audited(self):
        secret="http://operator:proxy-secret@proxy.example:8080"
        self.assertEqual(self.save(download_proxy_enabled="1",download_proxy_url=secret).status_code,303)
        with self.env.Session() as db:
            self.assertNotIn("proxy-secret",db.get(AppSetting,"download_proxy_url").value)
            self.assertEqual(get_proxy_url(db,"download"),secret)
            self.assertNotIn("proxy-secret",json.dumps(db.query(AuditLog).one().detail_json))
        self.assertNotIn("proxy-secret",self.client.get("/admin/settings/page").text)
        self.assertEqual(self.save(download_proxy_enabled="1",download_proxy_url="").status_code,303)
        with self.env.Session() as db:
            self.assertEqual(get_proxy_url(db,"download"),secret)

    def test_unchanged_proxy_address_is_not_resubmitted_with_other_settings(self):
        from app.services.system_settings import get_system_settings_view
        self.assertEqual(self.save(download_proxy_enabled="1",download_proxy_url="http://172.18.0.1:20172").status_code,303)
        with self.env.Session() as db:
            view={item['key']:item for item in get_system_settings_view(db)}
            self.assertEqual(view['download_proxy_url']['value'],'')
            self.assertEqual(view['download_proxy_url']['current_proxy'],'http://172.18.0.1:20172')
            payload={key:item['value'] or '' for key,item in view.items()}
        payload['max_running_jobs']='12'
        response=self.client.post('/admin/settings/update/form',data=payload,headers={'Origin':'http://testserver'},follow_redirects=False)
        self.assertEqual(response.status_code,303)
        with self.env.Session() as db:
            self.assertEqual(get_proxy_url(db,'download'),'http://172.18.0.1:20172')
            self.assertEqual(db.get(AppSetting,'max_running_jobs').value,'12')
        html=self.client.get('/admin/settings/page').text
        self.assertIn('name="download_proxy_url" value=""',html)
        self.assertIn('http://172.18.0.1:20172',html)

    def test_invalid_settings_roll_back_every_field(self):
        self.assertEqual(self.save(max_running_jobs="8").status_code,303)
        for changes in ({"video_download_concurrency":"0"},{"video_download_concurrency":"33"},
                        {"request_proxy_enabled":"1","request_proxy_url":"file:///etc/passwd"},
                        {"request_proxy_enabled":"1","request_proxy_url":""}):
            with self.subTest(changes=changes):
                response=self.save(max_running_jobs="9",**changes)
                self.assertEqual(response.status_code,400)
                self.assertTrue(response.json()["detail"])
                with self.env.Session() as db:
                    self.assertEqual(db.get(AppSetting,"max_running_jobs").value,"8")
                    self.assertEqual(db.query(AuditLog).count(),1)

    def test_ordinary_users_and_subadmins_cannot_read_or_write(self):
        for username in ("creator","reporter"):
            self.login(username)
            self.assertEqual(self.client.get("/admin/settings/page").status_code,403)
            self.assertEqual(self.save().status_code,403)
            response=self.client.post("/admin/settings/channels/form",data={"channel_limit_1":"10"},headers={"Origin":"http://testserver"})
            self.assertEqual(response.status_code,403)

    def test_cross_origin_settings_and_channel_writes_rejected(self):
        for path in ("/admin/settings/update/form","/admin/settings/channels/form"):
            response=self.client.post(path,data={"channel_limit_1":"10"},headers={"Origin":"https://outside.example"})
            self.assertEqual(response.status_code,403)
        with self.env.Session() as db:
            self.assertEqual(db.query(AppSetting).count(),0)
            self.assertEqual(db.query(AuditLog).count(),0)

    def test_channel_limits_update_existing_fields_and_validate_atomically(self):
        path="/admin/settings/channels/form"
        response=self.client.post(path,data={"channel_limit_1":"10","channel_limit_2":""},headers={"Origin":"http://testserver"},follow_redirects=False)
        self.assertEqual(response.status_code,303)
        response=self.client.post(path,data={"channel_limit_1":"7","channel_limit_2":"-1"},headers={"Origin":"http://testserver"})
        self.assertEqual(response.status_code,400)
        with self.env.Session() as db:
            self.assertEqual(db.get(ProviderKey,1).concurrent_limit,10)
            self.assertIsNone(db.get(ProviderKey,2).concurrent_limit)
            self.assertEqual(db.query(AuditLog).count(),1)

    def test_deleted_channels_are_not_shown_or_editable(self):
        with self.env.Session() as db:
            db.get(ProviderKey, 1).status = "deleted"
            db.commit()
        self.assertNotIn('name="channel_limit_1"', self.client.get("/admin/settings/page").text)
        response = self.client.post("/admin/settings/channels/form", data={"channel_limit_1": "10"}, headers={"Origin": "http://testserver"})
        self.assertEqual(response.status_code, 400)
        with self.env.Session() as db:
            self.assertEqual(db.get(ProviderKey, 1).concurrent_limit, 5)

    def test_download_limit_changes_without_restarting_or_cancelling_active_work(self):
        running={i:Future() for i in range(10)}
        for future in running.values(): future.set_running_or_notify_cancel()
        executor=MagicMock()
        executor.submit.side_effect=lambda *a,**kw:Future()
        with patch.object(worker_engine,"DOWNLOAD_CONCURRENCY",10),patch.object(worker_engine,"_DOWNLOAD_FUTURES",running),patch.object(worker_engine,"DOWNLOAD_EXECUTOR",executor):
            with self.env.Session() as db:
                upsert_system_setting(db,"video_download_concurrency","3",3);db.commit()
            with self.env.Session() as fresh:
                worker_engine._refresh_download_concurrency(fresh)
            self.assertEqual(worker_engine.DOWNLOAD_CONCURRENCY,3)
            self.assertFalse(worker_engine._schedule_download(100))
            self.assertTrue(all(not f.cancelled() for f in running.values()))
            for i in range(8): running[i].set_result(None)
            self.assertTrue(worker_engine._schedule_download(100))
            self.assertFalse(worker_engine._schedule_download(101))
            with self.env.Session() as db:
                upsert_system_setting(db,"video_download_concurrency","12",3);db.commit()
            with self.env.Session() as fresh: worker_engine._refresh_download_concurrency(fresh)
            self.assertTrue(worker_engine._schedule_download(101))


class ProxyTransportTests(unittest.TestCase):
    def test_proxy_validation(self):
        for url in ("http://127.0.0.1:20171","https://proxy.example:443","socks5://localhost:20170","socks5h://[::1]:20170"):
            self.assertEqual(validate_proxy_url(url),url)
        for url in ("ftp://host:21","http://host:0","http://host:99999","http://host:80/path","http://host:80?x=1","http://host:80\nproxy=x","http://u:%0ap@host:80"):
            with self.subTest(url=url),self.assertRaises(ValueError):validate_proxy_url(url)

    def test_status_and_create_use_request_proxy(self):
        client=MagicMock();client.__enter__.return_value=client
        client.get.return_value=httpx.Response(200,json={"id":"task-test","status":"processing"})
        client.post.return_value=httpx.Response(200,json={"id":"task-test","status":"queued"})
        with patch.object(sora_api.httpx,"Client",return_value=client) as constructor:
            sora_api.fetch_video_status("key","task-test",request_proxy="http://proxy:8080")
            self.assertEqual(constructor.call_args.kwargs["proxy"],"http://proxy:8080")
            self.assertFalse(constructor.call_args.kwargs["trust_env"])
            sora_api.create_video("key","prompt",12,"720x1280",request_proxy="")
            self.assertIsNone(constructor.call_args.kwargs["proxy"])

    def test_download_does_not_reuse_request_proxy(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(sora_api,"fetch_video_status",return_value=({"video_url":"https://video.example/file.mp4"},200,1)) as status,patch.object(sora_api,"_download_url",return_value=({},200,1)) as transfer:
            sora_api.download_video("key","task",Path(folder)/"v.mp4",request_proxy="http://request:8080",download_proxy="http://download:8081")
            self.assertEqual(status.call_args.kwargs["request_proxy"],"http://request:8080")
            self.assertEqual(transfer.call_args.args[3],"http://download:8081")

    def test_streaming_uses_download_proxy_after_request_proxy_status(self):
        client=MagicMock();client.send.return_value.status_code=200
        with patch.object(sora_api,"fetch_video_status",return_value=({"video_url":"https://video.example/file.mp4"},200,1)) as status,patch.object(sora_api.httpx,"Client",return_value=client) as constructor:
            sora_api.open_video_stream("key","task",request_proxy="http://request:8080",download_proxy="http://download:8081")
            self.assertEqual(status.call_args.kwargs["request_proxy"],"http://request:8080")
            self.assertEqual(constructor.call_args.kwargs["proxy"],"http://download:8081")


if __name__ == "__main__":unittest.main()
