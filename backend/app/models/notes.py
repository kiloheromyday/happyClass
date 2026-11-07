from uuid import UUID

from pydantic import Field, field_validator, model_validator

from backend.app.models.auth import StrictModel


class NoteFields(StrictModel):
    session_id: int | None = Field(default=None, strict=True, gt=0)
    title: str = Field(min_length=1, max_length=80)
    content: str = Field(min_length=1, max_length=5000)
    takeaway: str = Field(default='', max_length=300)
    next_step: str = Field(default='', max_length=300)
    reviewed: bool = Field(default=False, strict=True)

    @field_validator('title', 'content', 'takeaway', 'next_step')
    @classmethod
    def clean_text(cls, value):
        value = value.strip()
        if any(ord(char) < 32 and char not in '\n\t' for char in value):
            raise ValueError('请使用普通文字')
        return value

    @model_validator(mode='after')
    def nonempty(self):
        if not self.title or not self.content or '\n' in self.title or '\t' in self.title:
            raise ValueError('请填写标题和正文，标题请使用单行文字')
        return self


class NoteCreate(NoteFields):
    request_id: UUID


class NoteUpdate(NoteFields):
    version: int = Field(strict=True, ge=1)
