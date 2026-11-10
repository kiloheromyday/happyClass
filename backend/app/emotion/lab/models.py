from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from backend.app.models.auth import StrictModel

SessionId = Annotated[int, Field(gt=0, strict=True)]
Source = Literal['ALL', 'MANUAL', 'AI']
Scope = Literal['REAL', 'DEMO', 'ALL']
Alignment = Literal['RELATIVE', 'MINUTE', 'PHASE']


def text_value(value):
    value = value.strip()
    if any(ord(char) < 32 and char not in '\n\t' for char in value):
        raise ValueError('请使用普通文字')
    return value


class AnalysisSettings(StrictModel):
    source: Source = 'ALL'
    data_scope: Scope = 'REAL'
    alignment: Alignment = 'RELATIVE'
    bucket_minutes: int = Field(default=5, ge=1, le=30, strict=True)
    relative_bins: int = Field(default=10, ge=5, le=30, strict=True)
    min_records: int = Field(default=5, ge=3, le=1000, strict=True)
    concern_threshold: float = Field(default=0.6, ge=0.3, le=1, allow_inf_nan=False)
    include_after_class: bool = False


class StudyRequest(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    question: str = Field(default='', max_length=1200)
    tags: list[str] = Field(default_factory=list, max_length=5)
    session_ids: list[SessionId] = Field(min_length=1, max_length=24)
    baseline_ids: list[SessionId] = Field(default_factory=list, max_length=23)
    settings: AnalysisSettings = Field(default_factory=AnalysisSettings)
    version: int = Field(default=0, ge=0, strict=True)
    request_id: UUID

    _text = field_validator('title', 'question')(text_value)

    @field_validator('tags')
    @classmethod
    def clean_tags(cls, values):
        values = [text_value(value) for value in values]
        if any(not value or len(value) > 24 for value in values):
            raise ValueError('标签需为 1～24 字')
        if len(set(values)) != len(values):
            raise ValueError('标签不能重复')
        return values

    @model_validator(mode='after')
    def validate_selection(self):
        if not self.title:
            raise ValueError('请填写方案标题')
        if len(set(self.session_ids)) != len(self.session_ids):
            raise ValueError('课堂不能重复选择')
        if len(set(self.baseline_ids)) != len(self.baseline_ids):
            raise ValueError('基准课堂不能重复')
        if not set(self.baseline_ids).issubset(self.session_ids):
            raise ValueError('基准课堂必须位于所选课堂内')
        if len(self.baseline_ids) == len(self.session_ids):
            raise ValueError('至少保留一节非基准课堂')
        return self


class VersionRequest(StrictModel):
    version: int = Field(ge=1, strict=True)


class ArchiveRequest(VersionRequest):
    archived: bool


class RunRequest(StrictModel):
    version: int = Field(ge=1, strict=True)
    request_id: UUID


class ReportUpdate(VersionRequest):
    title: str = Field(min_length=1, max_length=120)
    status: Literal['DRAFT', 'REVIEWED', 'ARCHIVED'] = 'DRAFT'
    bookmarked: bool = False
    conclusion: str = Field(default='', max_length=4000)

    _text = field_validator('title', 'conclusion')(text_value)

    @model_validator(mode='after')
    def validate_review(self):
        if not self.title:
            raise ValueError('请填写报告标题')
        if self.status == 'REVIEWED' and not self.conclusion:
            raise ValueError('标记已复核前请填写教师结论')
        return self


class AnnotationRequest(StrictModel):
    section: Literal['FINDING', 'CONTEXT', 'LIMITATION', 'NEXT_STEP']
    content: str = Field(min_length=1, max_length=2000)
    version: int = Field(default=0, ge=0, strict=True)
    request_id: UUID

    _text = field_validator('content')(text_value)

    @model_validator(mode='after')
    def nonempty(self):
        if not self.content:
            raise ValueError('请填写批注内容')
        return self


TEMPLATES = [
    {
        'id': 'weekly-review',
        'title': '每周课堂情绪复盘',
        'question': '多节课堂中，哪些时段反复出现较多关注类别反馈？',
        'description': '以课堂进度对齐，查看跨课堂分布与重复出现的时段。',
        'settings': AnalysisSettings(alignment='RELATIVE').model_dump(),
        'tags': ['周复盘'],
    },
    {
        'id': 'teaching-phase',
        'title': '同类教学环节对比',
        'question': '相同名称的教学环节，在不同课堂里有怎样的反馈？',
        'description': '使用已标注的教学环节，按完全相同的环节名称对齐。',
        'settings': AnalysisSettings(alignment='PHASE').model_dump(),
        'tags': ['教学环节'],
    },
    {
        'id': 'source-quality',
        'title': '反馈来源与采样质量',
        'question': '主动反馈和 AI 采样是否覆盖了课堂，数据是否足够支撑比较？',
        'description': '分开观察两个来源的数量、时间覆盖和模型置信度分布。',
        'settings': AnalysisSettings(alignment='MINUTE', bucket_minutes=5).model_dump(),
        'tags': ['数据质量'],
    },
    {
        'id': 'baseline-comparison',
        'title': '基准组与对照组比较',
        'question': '两组课堂的反馈分布有哪些差异，哪些差异需要进一步核实？',
        'description': '选择基准课堂后，分别给出课堂等权和记录汇总的描述性结果。',
        'settings': AnalysisSettings(alignment='RELATIVE', min_records=10).model_dump(),
        'tags': ['课堂对比'],
    },
]
