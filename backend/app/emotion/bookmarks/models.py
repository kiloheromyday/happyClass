from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from backend.app.models.auth import StrictModel

Reason = Literal['REVISIT', 'PACE', 'EXAMPLE', 'CONCEPT', 'PRACTICE', 'OTHER']
MaterialState = Literal['DRAFT', 'PUBLISHED', 'ARCHIVED']
Minute = Annotated[int, Field(strict=True, ge=0, le=100000)]
Version = Annotated[int, Field(strict=True, ge=1)]
REASONS = {
    'REVISIT': '想再看一遍',
    'PACE': '节奏有点快',
    'EXAMPLE': '例题没跟上',
    'CONCEPT': '概念没弄懂',
    'PRACTICE': '练习不会做',
    'OTHER': '其他',
}


def tidy(value):
    value = value.strip()
    if any(ord(char) < 32 and char not in '\t\n' for char in value):
        raise ValueError('请检查文字中的特殊字符')
    return value


class CreateBookmark(StrictModel):
    request_id: UUID
    minute: Minute | None = None
    reason: Reason = 'REVISIT'
    title: str = Field(default='', max_length=100)
    note: str = Field(default='', max_length=2000)

    _tidy = field_validator('title', 'note')(tidy)


class BookmarkUpdate(StrictModel):
    version: Version
    reason: Reason
    title: str = Field(default='', max_length=100)
    note: str = Field(default='', max_length=2000)
    reviewed: bool

    _tidy = field_validator('title', 'note')(tidy)


class ResourceLink(StrictModel):
    label: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=1, max_length=1000)

    @field_validator('label')
    @classmethod
    def label_valid(cls, value):
        result = tidy(value)
        if not result:
            raise ValueError('请填写链接名称')
        return result

    @field_validator('url')
    @classmethod
    def url_valid(cls, value):
        value = value.strip()
        try:
            parsed = urlsplit(value)
            parsed.port
        except ValueError as error:
            raise ValueError('请输入有效的网页链接') from error
        if (
            parsed.scheme not in ('http', 'https') or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or '\\' in value or any(char.isspace() or ord(char) < 32 for char in value)
        ):
            raise ValueError('请填写以 http:// 或 https:// 开头的链接')
        return value


class MaterialContent(StrictModel):
    start_minute: Minute
    end_minute: Annotated[int, Field(strict=True, gt=0, le=100000)]
    title: str = Field(min_length=2, max_length=120)
    content: str = Field(default='', max_length=4000)
    links: list[ResourceLink] = Field(default_factory=list, max_length=5)

    _tidy = field_validator('title', 'content')(tidy)

    @model_validator(mode='after')
    def check_content(self):
        if self.start_minute >= self.end_minute:
            raise ValueError('结束分钟要晚于开始分钟')
        if len(self.title) < 2:
            raise ValueError('标题至少写两个字')
        if not self.content and not self.links:
            raise ValueError('请写一段讲解或添加资料链接')
        if len({item.url for item in self.links}) != len(self.links):
            raise ValueError('资料链接不能重复')
        return self


class CreateMaterial(MaterialContent):
    request_id: UUID
    publish: bool = False


class EditMaterial(MaterialContent):
    version: Version


class VersionChange(StrictModel):
    version: Version


class MaterialAction(VersionChange):
    action: Literal['PUBLISH', 'UNPUBLISH', 'ARCHIVE', 'RESTORE']


class MaterialProgress(StrictModel):
    completed: bool
    version: Version


class ReviewSelection(StrictModel):
    bookmark_ids: list[Annotated[int, Field(gt=0, strict=True)]] = Field(min_length=1, max_length=30)
    reviewed: bool

    @field_validator('bookmark_ids')
    @classmethod
    def unique_ids(cls, values):
        if len(set(values)) != len(values):
            raise ValueError('同一条书签只能选择一次')
        return values
