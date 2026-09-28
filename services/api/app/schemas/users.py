import base64
import re
from datetime import datetime
from typing import Optional

from pydantic import Field, field_validator

from .common import CamelModel

# PNG/JPEG/WEBP/GIF only -- deliberately excludes image/svg+xml, which can
# carry an embedded <script> and would be a stored-XSS vector if ever
# rendered as anything other than a plain <img src>.
_AVATAR_DATA_URL_RE = re.compile(r'^data:image/(png|jpe?g|webp|gif);base64,([A-Za-z0-9+/]+=*)$')
# A generous cap on the *decoded* image, not the base64 text -- this is
# meant to be a client-cropped square avatar (a few hundred KB at most), not
# a limit anyone should ever legitimately hit; it exists to stop a garbage
# or hostile payload from bloating the users table.
_AVATAR_MAX_DECODED_BYTES = 3 * 1024 * 1024

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
    avatar_url: Optional[str] = None


class RegisterIn(CamelModel):
    email: str
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(default='', max_length=200)
    # Only checked when the deployment has REGISTER_INVITE_CODE set (see
    # app/config.py) -- '' otherwise, matching the open-by-default rule.
    invite_code: str = Field(default='', max_length=200)

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


class UpdateProfileIn(CamelModel):
    """PATCH /api/auth/me -- a user editing their own account. Distinct
    from UpdateRoleIn, which only an owner can apply to someone else.
    Every field is optional and independent: send just displayName to
    rename yourself, or currentPassword+newPassword together to change
    your password, or both at once."""

    display_name: Optional[str] = Field(default=None, max_length=200)
    current_password: Optional[str] = None
    new_password: Optional[str] = Field(default=None, min_length=8, max_length=200)


class UpdateAvatarIn(CamelModel):
    """PUT /api/auth/me/avatar -- the frontend crops the photo to a square
    on-canvas first, so this always receives an already-small image, not a
    raw upload straight off disk."""

    avatar_data_url: str

    @field_validator('avatar_data_url')
    @classmethod
    def _validate_avatar_data_url(cls, value: str) -> str:
        match = _AVATAR_DATA_URL_RE.match(value)
        if not match:
            raise ValueError('Must be a data:image/(png|jpeg|webp|gif);base64,... URI.')
        decoded_length = len(base64.b64decode(match.group(2), validate=True))
        if decoded_length > _AVATAR_MAX_DECODED_BYTES:
            raise ValueError(f'Image is too large ({decoded_length} bytes decoded, {_AVATAR_MAX_DECODED_BYTES} max).')
        return value
