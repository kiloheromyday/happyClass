from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from backend.app.models.auth import StrictModel
from backend.app.models.classroom import Emotion

PositiveId = Annotated[int, Field(gt=0, strict=True)]
Version = Annotated[int, Field(ge=1, strict=True)]
Reason = Literal[
    'PACE_FAST', 'PACE_SLOW', 'NEED_EXAMPLE', 'UNCLEAR', 'EXERCISE_HARD',
    'CONTENT_DENSE', 'AUDIO_VISUAL', 'TIRED', 'GROUP_WORK', 'POSITIVE', 'OTHER',
]
CaseState = Literal[
    'NEW', 'ACKNOWLEDGED', 'IN_PROGRESS', 'WAITING_STUDENT',
    'WAITING_REVIEW', 'RESOLVED', 'WITHDRAWN',
]


def clean_text(value):
    value = value.strip()
    if any(ord(char) < 32 and char not in '\n\t' for char in value):
        raise ValueError('请使用普通文字')
    return value


class Command(StrictModel):
    request_id: UUID


class VersionCommand(Command):
    version: Version


class CreateCase(Command):
    session_id: PositiveId
    emotion: Emotion
    reasons: list[Reason] = Field(min_length=1, max_length=3)
    title: str = Field(min_length=2, max_length=120)
    content: str = Field(default='', max_length=2000)
    impact: Literal['LOW', 'MEDIUM', 'HIGH'] = 'MEDIUM'
    topic_minute: int | None = Field(default=None, ge=0, le=100000, strict=True)
    linked_record_id: PositiveId | None = None

    _clean = field_validator('title', 'content')(clean_text)

    @model_validator(mode='after')
    def meaningful(self):
        if len(self.title) < 2:
            raise ValueError('标题至少两个字')
        if len(self.reasons) != len(set(self.reasons)):
            raise ValueError('原因不能重复')
        if 'OTHER' in self.reasons and not self.content:
            raise ValueError('选择其他原因时，请补充说明')
        return self


class EditCase(VersionCommand):
    title: str = Field(min_length=2, max_length=120)
    content: str = Field(default='', max_length=2000)
    emotion: Emotion
    reasons: list[Reason] = Field(min_length=1, max_length=3)
    impact: Literal['LOW', 'MEDIUM', 'HIGH'] = 'MEDIUM'

    _clean = field_validator('title', 'content')(clean_text)

    @model_validator(mode='after')
    def meaningful(self):
        if len(self.title) < 2 or len(set(self.reasons)) != len(self.reasons):
            raise ValueError('请检查标题及原因')
        if 'OTHER' in self.reasons and not self.content:
            raise ValueError('其他原因需要补充说明')
        return self


class CaseAction(VersionCommand):
    action: Literal[
        'ACKNOWLEDGE', 'START', 'ASK_STUDENT', 'RESOLVE', 'REOPEN', 'WITHDRAW',
    ]
    content: str = Field(default='', max_length=2000)

    _clean = field_validator('content')(clean_text)


class MessageCreate(Command):
    content: str = Field(min_length=1, max_length=2000)
    visibility: Literal['SHARED', 'STAFF'] = 'SHARED'
    template_id: PositiveId | None = None

    _clean = field_validator('content')(clean_text)

    @model_validator(mode='after')
    def nonempty(self):
        if not self.content:
            raise ValueError('请填写回应内容')
        return self


class MessageEdit(VersionCommand):
    content: str = Field(min_length=1, max_length=2000)

    _clean = field_validator('content')(clean_text)

    @model_validator(mode='after')
    def nonempty(self):
        if not self.content:
            raise ValueError('请填写回应内容')
        return self


class ReviewCreate(VersionCommand):
    prompt: str = Field(min_length=2, max_length=1000)
    due_days: int = Field(default=3, ge=1, le=14, strict=True)

    _clean = field_validator('prompt')(clean_text)

    @model_validator(mode='after')
    def nonempty(self):
        if len(self.prompt) < 2:
            raise ValueError('请填写回访问题')
        return self


class ReviewAnswer(Command):
    outcome: Literal['HELPED', 'PARTLY', 'UNCHANGED']
    emotion: Emotion | None = None
    content: str = Field(default='', max_length=1500)

    _clean = field_validator('content')(clean_text)


class ReviewClose(VersionCommand):
    content: str = Field(default='', max_length=1000)

    _clean = field_validator('content')(clean_text)


class ManageCase(VersionCommand):
    priority: Literal['NORMAL', 'HIGH'] = 'NORMAL'
    tags: list[str] = Field(default_factory=list, max_length=5)
    watch: bool | None = None

    @field_validator('tags')
    @classmethod
    def tags_valid(cls, values):
        values = [clean_text(value) for value in values]
        if len(set(values)) != len(values) or any(not value or len(value) > 24 for value in values):
            raise ValueError('标签需唯一且每个 1～24 字')
        return values


class LinkAdjustment(VersionCommand):
    adjustment_id: PositiveId
    public_summary: str = Field(min_length=2, max_length=1000)

    _clean = field_validator('public_summary')(clean_text)

    @model_validator(mode='after')
    def meaningful(self):
        if len(self.public_summary) < 2:
            raise ValueError('请填写可向学生展示的调整说明')
        return self


class GroupCreate(Command):
    session_id: PositiveId
    title: str = Field(min_length=2, max_length=120)
    description: str = Field(default='', max_length=2000)
    case_ids: list[PositiveId] = Field(min_length=1, max_length=50)

    _clean = field_validator('title', 'description')(clean_text)

    @model_validator(mode='after')
    def unique(self):
        if len(self.title) < 2 or len(set(self.case_ids)) != len(self.case_ids):
            raise ValueError('请检查标题及反馈单选择')
        return self


class GroupUpdate(VersionCommand):
    title: str = Field(min_length=2, max_length=120)
    description: str = Field(default='', max_length=2000)
    case_ids: list[PositiveId] = Field(min_length=1, max_length=50)
    archived: bool = False

    _clean = field_validator('title', 'description')(clean_text)

    @model_validator(mode='after')
    def unique(self):
        if len(self.title) < 2 or len(set(self.case_ids)) != len(self.case_ids):
            raise ValueError('请检查标题及反馈单选择')
        return self


class BatchMember(StrictModel):
    case_id: PositiveId
    version: Version


class BatchAction(VersionCommand):
    action: Literal['REPLY', 'ACKNOWLEDGE', 'START', 'REQUEST_REVIEW']
    members: list[BatchMember] = Field(min_length=1, max_length=50)
    content: str = Field(min_length=2, max_length=2000)
    due_days: int = Field(default=3, ge=1, le=14, strict=True)

    _clean = field_validator('content')(clean_text)

    @model_validator(mode='after')
    def unique(self):
        if len(self.content) < 2 or len({item.case_id for item in self.members}) != len(self.members):
            raise ValueError('请填写处理说明并避免重复选择')
        return self


class ReplyTemplate(Command):
    title: str = Field(min_length=2, max_length=120)
    content: str = Field(min_length=2, max_length=2000)
    reason: Reason | None = None
    version: int = Field(default=0, ge=0, strict=True)
    archived: bool = False

    _clean = field_validator('title', 'content')(clean_text)

    @model_validator(mode='after')
    def meaningful(self):
        if min(len(self.title), len(self.content)) < 2:
            raise ValueError('请填写模板标题与内容')
        return self


class PolicyUpdate(Command):
    version: int = Field(default=0, ge=0, strict=True)
    response_hours: int = Field(default=24, ge=1, le=168, strict=True)
    review_days: int = Field(default=3, ge=1, le=14, strict=True)
    submit_grace_hours: int = Field(default=72, ge=0, le=168, strict=True)
    daily_case_limit: int = Field(default=5, ge=1, le=20, strict=True)
    reopen_days: int = Field(default=7, ge=1, le=14, strict=True)


class SavedView(Command):
    title: str = Field(min_length=2, max_length=80)
    filters: dict = Field(default_factory=dict)
    version: int = Field(default=0, ge=0, strict=True)

    _clean = field_validator('title')(clean_text)

    @model_validator(mode='after')
    def nonempty(self):
        if len(self.title) < 2:
            raise ValueError('请填写筛选视图名称')
        return self


class Filters(StrictModel):
    session_id: PositiveId | None = None
    course_id: PositiveId | None = None
    state: CaseState | Literal['ALL'] = 'ALL'
    reason: Reason | Literal['ALL'] = 'ALL'
    emotion: Emotion | Literal['ALL'] = 'ALL'
    priority: Literal['ALL', 'NORMAL', 'HIGH'] = 'ALL'
    search: str = Field(default='', max_length=120)
    watched: bool = False
    overdue: bool = False
    review_overdue: bool = False
    active_only: bool = False
    data_scope: Literal['ALL', 'REAL', 'DEMO'] = 'ALL'
    sort: Literal['UPDATED', 'CREATED', 'OLDEST', 'PRIORITY'] = 'UPDATED'

    _clean = field_validator('search')(clean_text)
