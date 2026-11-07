from uuid import UUID

from pydantic import Field, field_validator

from backend.app.models.auth import StrictModel


class JoinCodeCreate(StrictModel):
    version: int = Field(strict=True, ge=0)
    ttl_minutes: int = Field(default=60, strict=True, ge=15, le=1440)
    request_id: UUID


class JoinClassroom(StrictModel):
    code: str = Field(min_length=1, max_length=20)

    @field_validator('code')
    @classmethod
    def normalize(cls, value):
        value = value.replace('-', '').replace(' ', '').strip().upper()
        if len(value) != 8 or any(char not in 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789' for char in value):
            raise ValueError('请填写 8 位有效加入码')
        return value
