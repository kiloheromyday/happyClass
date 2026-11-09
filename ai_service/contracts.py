from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FaceResult(BaseModel):
    model_config = ConfigDict(extra='forbid')
    emotion: Literal['NEUTRAL', 'HAPPY', 'SURPRISED', 'SAD', 'ANGRY', 'DISGUST', 'FEAR', 'CONTEMPT']
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)


class InferenceFace(FaceResult):
    candidates: list[FaceResult] = Field(default_factory=list, max_length=3)


class InferenceResult(BaseModel):
    model_config = ConfigDict(extra='forbid')
    detected: int = Field(ge=0, le=10000)
    processed: int = Field(ge=0, le=12)
    faces: list[InferenceFace] = Field(max_length=12)

    @model_validator(mode='after')
    def consistent_counts(self):
        if self.processed != len(self.faces) or self.detected < self.processed:
            raise ValueError('Inconsistent face counts')
        return self
