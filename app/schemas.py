from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str
    next: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = 'bearer'


class AdminCreateUserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6)
    role: str = 'user'
    display_name: str | None = None


class AdminGrantQuotaRequest(BaseModel):
    amount: int = Field(gt=0)
    note: str | None = None


class AdminResetPasswordRequest(BaseModel):
    password: str = Field(min_length=6)


class AdminCreateProviderKeyRequest(BaseModel):
    name: str
    raw_key: str
    provider_name: str = 'sora_api'
    api_base_url: str = 'https://niubi.zeabur.app'
    model_id: str = ''
    model_id_4s: str | None = None
    model_id_5s: str | None = None
    model_id_8s: str | None = None
    model_id_10s: str | None = None
    model_id_12s: str | None = None
    model_id_15s: str | None = None
    weight: int = 100
    daily_limit: int | None = None
    concurrent_limit: int | None = None


class CreateJobRequest(BaseModel):
    prompt: str = Field(min_length=1)
    product_name: str = Field(min_length=1, max_length=80)
    region_name: str = Field(min_length=1, max_length=80)
    seconds: int
    size: str
    reference_image_url: str | None = None
    reference_video_url: str | None = None
    reference_preset_id: int | None = None


class ActionResponse(BaseModel):
    ok: bool
    message: str
