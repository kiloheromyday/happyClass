from typing import Annotated, Literal
from pydantic import Field, field_validator, model_validator
from backend.app.models.auth import StrictModel


class BuddyRequest(StrictModel):
    user_id: Annotated[int, Field(gt=0, strict=True)]


class BuddySearch(StrictModel):
    username: str | None = Field(default=None, min_length=3, max_length=254, pattern=r'^[A-Za-z0-9_][A-Za-z0-9_.@+\-]*$')
    q: str = Field(default='', max_length=120)
    scope: Literal['all', 'username', 'nickname', 'interests', 'bio', 'major', 'grade', 'study_goal', 'learning_style'] = 'all'
    interests: str = Field(default='', max_length=80)
    major: str = Field(default='', max_length=60)
    grade: str = Field(default='', max_length=20)
    learning_style: Literal['', 'pair', 'questions', 'project', 'focus'] = ''
    relationship: Literal['all', 'new', 'friends', 'pending'] = 'all'
    common_course: bool = False
    limit: int = Field(default=12, ge=1, le=24)
    offset: int = Field(default=0, ge=0, le=10000)

    @field_validator('q', 'interests', 'major', 'grade')
    @classmethod
    def clean_query(cls, value):
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError('请使用普通文字查找')
        return value.strip()

    @model_validator(mode='after')
    def meaningful_search(self):
        if not any((self.username, self.q, self.interests, self.major, self.grade, self.learning_style, self.common_course, self.relationship != 'all')):
            raise ValueError('请填写关键词或选择筛选条件')
        if len(self.q.split()) > 5:
            raise ValueError('关键词最多五组，请精简后查找')
        return self
