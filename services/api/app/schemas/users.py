import re
from datetime import datetime

from pydantic import Field, field_validator

from .common import CamelModel

# Deliberately a plain str + this regex rather than pydantic's EmailStr,
# which needs the extra `email-validator` package — not worth a new
# dependency for a format check this simple. Good enough to reject garbage,
# not meant to be a full RFC 5322 validator (real confirmation would be an
# actual verification email, which is out of scope here).
_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _validate_email(value: str) -> str:
    value = value.strip()
    if not _EMAIL_RE.match(value):
        raise ValueError('Not a valid email address.')
    return value.lower()


class UserOut(CamelModel):
    """Never carries password_hash — this is the only shape a user record is
    ever sent to a client in."""

    user_id: str
    email: str
    display_name: str
    role: str
    created_at: datetime


class RegisterIn(CamelModel):
    email: str
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(default='', max_length=200)

    _normalize_email = field_validator('email')(_validate_email)


class LoginIn(CamelModel):
    email: str
    password: str

    _normalize_email = field_validator('email')(_validate_email)


class TokenOut(CamelModel):
    access_token: str
    token_type: str = 'bearer'
    user: UserOut


class UpdateRoleIn(CamelModel):
    role: str
