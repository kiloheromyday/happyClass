from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import AwareDatetime, Field, StringConstraints, model_validator
from backend.app.models.auth import StrictModel

PositiveID = Annotated[int, Field(gt=0, strict=True)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class Emotion(StrEnum):
    HAPPY = 'HAPPY'
    NEUTRAL = 'NEUTRAL'
    SAD = 'SAD'
    ANGRY = 'ANGRY'
    SURPRISED = 'SURPRISED'
    FEAR = 'FEAR'
    DISGUST = 'DISGUST'


class CourseRequest(StrictModel):
    name: Title
    teacher_id: PositiveID
    department_id: str | None = Field(default=None, min_length=1, max_length=32)


class CourseCreateRequest(CourseRequest):
    request_id: UUID | None = None


class SessionRequest(StrictModel):
    request_id: UUID | None = None
    course_id: PositiveID
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    classroom: Title
    class_name: Title

    @model_validator(mode='after')
    def valid_interval(self):
        if self.ends_at <= self.starts_at:
            raise ValueError('结束时间必须晚于开始时间')
        return self


class ScheduleRequest(StrictModel):
    user_ids: list[PositiveID] = Field(max_length=500)


class TeachingSessionRequest(SessionRequest):
    request_id: UUID


class EmojiRequest(StrictModel):
    session_id: PositiveID
    emotion: Emotion
    request_id: UUID


def utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def now_utc() -> datetime:
    return datetime.now(UTC)
