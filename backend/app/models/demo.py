from typing import Literal
from pydantic import Field, field_validator
from backend.app.models.auth import StrictModel, RegisterRequest, ProfileRequest, valid_password


class DemoLoginRequest(StrictModel):
    username: Literal['demo_student', 'demo_teacher', 'demo_admin']


class MemberUpdateRequest(StrictModel):
    nickname: str = Field(default='', max_length=32)
    email: str | None = Field(default=None, max_length=254)
    expected_email: str | None = Field(default=None, max_length=254)
    expected_nickname: str = Field(default='', max_length=32)
    _email = field_validator('email', 'expected_email')(RegisterRequest.validate_email.__func__)
    _nickname = field_validator('nickname', 'expected_nickname')(ProfileRequest.clean_text.__func__)


class MemberStatusRequest(StrictModel):
    status: Literal['ACTIVE', 'DISABLED']
    expected_status: Literal['ACTIVE', 'DISABLED']


class MemberPasswordRequest(StrictModel):
    new_password: str = Field(min_length=10, max_length=128)
    _password = field_validator('new_password')(lambda value: valid_password(value))
