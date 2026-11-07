from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator
from backend.app.models.auth import StrictModel
from backend.app.models.classroom import PositiveID


def clean(value):
    value = value.strip()
    if any(ord(char) < 32 and char != '\n' for char in value):
        raise ValueError('请使用普通文字')
    return value


class LeaveRequest(StrictModel):
    session_id: PositiveID
    category: Literal['SICK', 'PERSONAL', 'OTHER']
    reason: str = Field(min_length=2, max_length=500)
    request_id: UUID

    @field_validator('reason', mode='before')
    @classmethod
    def reason_text(cls, value):
        return clean(value) if isinstance(value, str) else value


class LeaveVersion(StrictModel):
    version: int = Field(ge=1, strict=True)


class LeaveDecision(LeaveVersion):
    decision: Literal['APPROVED', 'REJECTED']
    reply: str = Field(default='', max_length=500)

    @field_validator('reply', mode='before')
    @classmethod
    def reply_text(cls, value):
        return clean(value) if isinstance(value, str) else value

    @model_validator(mode='after')
    def rejection_requires_reason(self):
        if self.decision == 'REJECTED' and not self.reply:
            raise ValueError('驳回时请填写原因')
        return self
