import tempfile
from pathlib import Path
from unittest.mock import patch

from account_settings_support import AccountTestEnvironment
from app.api.admin.routes import router
from app.core.config import settings
from app.models.tables import AppSetting, ProviderKey


class SystemSettingsEnvironment(AccountTestEnvironment):
    def __init__(self):
        super().__init__()
        self.secret_dir = tempfile.TemporaryDirectory()
        secret_patch = patch.object(settings, "key_encryption_secret_file", str(Path(self.secret_dir.name) / "key"))
        secret_patch.start()
        self.patches.append(secret_patch)
        AppSetting.__table__.create(self.engine)
        ProviderKey.__table__.create(self.engine)
        with self.Session() as db:
            db.add_all([ProviderKey(id=i, name=name, provider_name=provider, key_masked="***", key_encrypted="test", concurrent_limit=limit)
                        for i, name, provider, limit in [(1,"Veo 测试通道","veo_omni",5),(2,"长名称通道 · 备用网络与生成服务","wuyin_omni",None)]])
            db.commit()
        self.app.include_router(router)

    def close(self):
        super().close()
        self.secret_dir.cleanup()
