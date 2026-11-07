from typing import Annotated
from uuid import UUID
from pydantic import Field, StringConstraints, field_validator
from backend.app.models.auth import StrictModel
from backend.app.models.classroom import CourseRequest

Score = Annotated[int, Field(strict=True, ge=1, le=5)]
Version = Annotated[int, Field(strict=True, ge=0)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class EvaluationRequest(StrictModel):
    clarity: Score
    pace: Score
    engagement: Score
    gain: Score
    comment: str = Field(default='', max_length=1000)
    version: Version
    request_id: UUID

    @field_validator('comment')
    @classmethod
    def ordinary_text(cls, value):
        if any(ord(char) < 32 and char not in '\n\t' for char in value):
            raise ValueError('请填写普通文字')
        return value.strip()


class DepartmentRequest(StrictModel):
    id: str = Field(pattern=r'^[a-z][a-z0-9_-]{1,31}$')
    name: Name
    short_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=12)]
    color: str = Field(pattern=r'^#[0-9a-fA-F]{6}$')
    version: Version = 0


class CourseUpdate(CourseRequest):
    version: Annotated[int, Field(strict=True, ge=1)]
    archived: bool = Field(strict=True)
