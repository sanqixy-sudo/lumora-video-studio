import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from app.api.user.routes import _model_options, _parse_model_choice, _select_model_provider_key, _resolve_job_reference_materials
from app.api.admin.routes import _provider_base_url, toggle_provider_key_form, update_provider_key_form
from app.models.tables import ProviderKey
from app.services.provider_keys import provider_is_retired, select_provider_key
from app.services.jobs import create_jobs_batch_and_reserve, create_job_and_charge


class ProviderRetirementTests(unittest.TestCase):
    def test_aliases_cannot_create_new_tasks(self):
        for alias in ['podsora','pod_sora','apipod','apipod_sora','podgrok','pod_grok','grok','grok_imagine']:
            with self.subTest(alias=alias):
                self.assertTrue(provider_is_retired(alias))
                with self.assertRaises(HTTPException): _parse_model_choice(alias+':12',12)
                with self.assertRaises(HTTPException): _provider_base_url(alias,'https://example.com')

    def test_old_keys_are_not_selectable(self):
        retired=ProviderKey(id=9,name='old',provider_name='podgrok',status='active',model_id_12s='grok')
        live=ProviderKey(id=1,name='Sora',provider_name='sora_api',status='active',model_id_12s='sora-2-12s')
        db=MagicMock(); db.query.return_value.filter.return_value.order_by.return_value.all.return_value=[retired,live]
        self.assertEqual([item['provider_name'] for item in _model_options(db)],['sora_api'])
        db.query.return_value.filter.return_value.first.return_value=retired
        with self.assertRaises(HTTPException): _select_model_provider_key(db,'',12,9)
        with patch('app.services.provider_keys.list_active_provider_keys',return_value=[retired]):
            self.assertIsNone(select_provider_key(db,'podgrok',12))

    def test_retired_key_cannot_be_reenabled_or_changed_to_other_provider(self):
        db=MagicMock(); db.query.return_value.filter.return_value.first.return_value=ProviderKey(id=9,provider_name='podsora',status='disabled')
        with self.assertRaises(HTTPException): toggle_provider_key_form(9,MagicMock(),db)
        with self.assertRaises(HTTPException): update_provider_key_form(key_id=9,name='renamed',provider_name='sora_api',db=db,admin=MagicMock())
        db.commit.assert_not_called()

    def test_service_rejects_retired_keys_before_reserving_quota(self):
        key=ProviderKey(id=9,provider_name='podsora'); db=MagicMock(); user=MagicMock(id=1)
        with self.assertRaises(ValueError): create_jobs_batch_and_reserve(db,user,key,['prompt'],12,'720x1280')
        db.add.assert_not_called()
        db.query.return_value.filter.return_value.first.return_value=None
        with self.assertRaises(ValueError): create_job_and_charge(db,user,key,'prompt',12,'720x1280')
        db.add.assert_not_called()

    def test_veo_video_inputs_rejected_before_resolving_images(self):
        for kwargs in [{'omni_mode':'video_edit'},{'reference_video_url':'https://cdn.example/a.mp4'},{'omni_reference_video_url':'https://cdn.example/a.mp4'}]:
            with patch('app.api.user.routes._resolve_reference_image_url') as image:
                with self.assertRaises(HTTPException): _resolve_job_reference_materials(MagicMock(),MagicMock(),'veo_omni','720x1280',**kwargs)
                image.assert_not_called()

    def test_wuyin_video_still_allowed(self):
        images,video=_resolve_job_reference_materials(MagicMock(),MagicMock(),'wuyin_omni','720x1280',omni_reference_video_url='https://cdn.example/a.mp4')
        self.assertEqual(images,[]); self.assertEqual(video,'https://cdn.example/a.mp4')

if __name__=='__main__': unittest.main()
