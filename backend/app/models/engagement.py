from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from backend.app.models.auth import StrictModel

Category = Literal['PACE', 'EXAMPLE', 'REPEAT', 'OTHER']


class QuestionRequest(StrictModel):
    category: Category
    text: str = Field(default='', max_length=300)
    request_id: UUID

    @field_validator('text')
    @classmethod
    def clean_text(cls, value):
        value = value.strip()
        if any(ord(char) < 32 and char not in '\n\t' for char in value):
            raise ValueError('请使用普通文字')
        return value


class AnswerRequest(StrictModel):
    reply: str = Field(default='', max_length=1000)
    status: Literal['OPEN', 'RESOLVED']
    version: int = Field(strict=True, ge=1)

    _clean = field_validator('reply')(QuestionRequest.clean_text.__func__)


class ReflectionRequest(StrictModel):
    reflection: str = Field(max_length=2000)
    version: int = Field(strict=True, ge=0)

    _clean = field_validator('reflection')(QuestionRequest.clean_text.__func__)


class GuideRequest(StrictModel):
    title: str = Field(default='', max_length=80)
    content: str = Field(default='', max_length=3000)
    practice: str = Field(default='', max_length=1500)
    version: int = Field(strict=True, ge=0)
    action: Literal['SAVE', 'PUBLISH', 'UNPUBLISH'] = 'SAVE'

    _clean = field_validator('title', 'content', 'practice')(QuestionRequest.clean_text.__func__)
