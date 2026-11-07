from datetime import UTC
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator

from ai_service.contracts import FaceResult
from backend.app.models.auth import StrictModel
from backend.app.models.classroom import PositiveID


class AiBatchRequest(StrictModel):
    batch_id: UUID
    session_id: PositiveID
    device_id: str = Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9][A-Za-z0-9_.:\-]*$')
    captured_at: AwareDatetime
    faces: list[FaceResult] = Field(max_length=12)

    @field_validator('captured_at')
    @classmethod
    def normalize_time(cls, value):
        return value.astimezone(UTC)
