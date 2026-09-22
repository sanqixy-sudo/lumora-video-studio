"""Real creation/settings routes backed by an isolated database for verification."""
from app.api.user.routes import router
from app.models.tables import (ProviderKey, QuotaWallet, ReferenceImagePreset, Job, JobBatch, JobFile,
                               QuotaPlan, UserQuotaPlanAssignment, JobQuotaReservation, PackageQuotaLedger, QuotaLedger)
from system_settings_support import SystemSettingsEnvironment


class CreationFeaturesEnvironment(SystemSettingsEnvironment):
    def __init__(self):
        super().__init__()
        for model in (QuotaWallet,ReferenceImagePreset,JobBatch,Job,JobFile,QuotaPlan,UserQuotaPlanAssignment,JobQuotaReservation,PackageQuotaLedger,QuotaLedger):
            model.__table__.create(self.engine)
        with self.Session() as db:
            db.get(ProviderKey, 1).model_id_10s = 'veo-omni-flash'
            db.add_all([QuotaWallet(id=i,user_id=i,remaining_quota=100,total_granted=100) for i in (1,2,3)])
            for i,name in enumerate(['310 Scores','Ace Breaker Rush','Arrow Stack Clear','中文素材','<script>测试</script>'],1):
                db.add(ReferenceImagePreset(id=i,name=name,owner_user_id=1,image_url='/static/brand/lumora-mark.svg',width=720,height=1280,aspect_ratio='9:16'))
            db.commit()
        self.app.include_router(router)
