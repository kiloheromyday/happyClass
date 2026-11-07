from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from backend.app.models.auth import StrictModel


class WallText(StrictModel):
    content: str = Field(min_length=1, max_length=600)

    @field_validator('content')
    @classmethod
    def clean_content(cls, value):
        value = value.strip()
        if not value or any(ord(char) < 32 and char not in '\n\t' for char in value):
            raise ValueError('请填写普通文字留言')
        return value


class WallCreate(WallText):
    visibility: Literal['ANONYMOUS', 'REVEALABLE'] = 'ANONYMOUS'
    request_id: UUID


class WallUpdate(WallText):
    version: int = Field(strict=True, ge=1)
