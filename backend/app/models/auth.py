import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


def valid_password(value: str) -> str:
    if len(value) < 10 or len(value) > 128 or not any(c.isalpha() for c in value) or not any(c.isdigit() for c in value):
        raise ValueError("密码需为 10～128 位，包含字母和数字")
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginRequest(StrictModel):
    username: str = Field(min_length=3, max_length=254, pattern=r"^[A-Za-z0-9_][A-Za-z0-9_.@+\-]*$")
    password: str = Field(min_length=1, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value):
        return value.casefold()


class RegisterRequest(LoginRequest):
    email: str | None = Field(default=None, max_length=254)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value):
        return valid_password(value)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value):
        if value is None or not value.strip():
            return None
        value = value.strip().casefold()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise ValueError("邮箱格式不正确")
        return value


class AdminCreateUserRequest(RegisterRequest):
    role: Literal['TEACHER', 'STUDENT']


class PasswordRequest(StrictModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, value):
        return valid_password(value)


class ProfileRequest(StrictModel):
    nickname: str = Field(default='', max_length=32)
    email: str | None = Field(default=None, max_length=254)
    bio: str = Field(default='', max_length=160)
    interests: str = Field(default='', max_length=80)
    avatar_color: Literal['sage', 'sand', 'sky', 'lilac', 'rose'] = 'sage'
    major: str = Field(default='', max_length=60)
    grade: str = Field(default='', max_length=20)
    study_goal: str = Field(default='', max_length=100)
    learning_style: Literal['', 'pair', 'questions', 'project', 'focus'] = ''

    @field_validator('email')
    @classmethod
    def validate_email(cls, value):
        return RegisterRequest.validate_email(value)

    @field_validator('nickname', 'bio', 'interests', 'major', 'grade', 'study_goal')
    @classmethod
    def clean_text(cls, value):
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError('请使用普通文字填写资料')
        return value.strip()
