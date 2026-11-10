from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from backend.app.models.auth import StrictModel


class InsightRules(StrictModel):
    bucket_minutes: Literal[1, 5, 10] = 5
    min_records: int = Field(default=5, ge=3, le=1000, strict=True)
    concern_ratio: float = Field(default=0.6, ge=0.3, le=1, allow_inf_nan=False)
    consecutive_windows: int = Field(default=2, ge=2, le=6, strict=True)
    version: int = Field(default=0, ge=0, strict=True)


class InsightEntry(StrictModel):
    kind: Literal['PHASE', 'ACTION']
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(default='', max_length=2000)
    start_minute: int = Field(ge=0, le=100000, strict=True)
    end_minute: int = Field(ge=0, le=100000, strict=True)
    status: Literal['PLANNED', 'DONE', 'CANCELLED'] = 'PLANNED'
    outcome: str = Field(default='', max_length=2000)
    version: int = Field(default=0, ge=0, strict=True)
    request_id: UUID

    @field_validator('title', 'content', 'outcome')
    @classmethod
    def plain_text(cls, value):
        value = value.strip()
        if any(ord(char) < 32 and char not in '\n\t' for char in value):
            raise ValueError('请使用普通文字')
        return value

    @model_validator(mode='after')
    def interval(self):
        if not self.title:
            raise ValueError('请填写标题')
        if self.end_minute < self.start_minute:
            raise ValueError('结束时间不能早于开始时间')
        if self.kind == 'PHASE' and self.end_minute == self.start_minute:
            raise ValueError('教学环节需包含至少一分钟')
        if self.kind == 'ACTION' and self.end_minute != self.start_minute:
            raise ValueError('教学调整请使用同一个发生时刻')
        return self
