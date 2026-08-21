"""Password hashing and access-token issuing for real multi-user auth
(Phase 3). Two deliberate choices worth calling out:

- **PBKDF2-HMAC-SHA256** (stdlib `hashlib`, no bcrypt/argon2) for password
  hashing — avoids a compiled dependency (bcrypt needs one; argon2 needs
  argon2-cffi) for a service that otherwise has none. 260,000 iterations
  matches Django's current default, which is a reasonable, well-reviewed
  baseline as of this writing.
- **Real JWTs** (via PyJWT), not a bespoke signed-token format — so a future
  migration to Supabase Auth (noted as an open option in db/schema.sql) can
  reuse the same token shape/claims rather than inventing a second one.
"""

import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass
from typing import Optional

import jwt

_PBKDF2_ITERATIONS = 260_000
_PBKDF2_ALGO = 'sha256'

# Local-dev-only default, same pattern as config.DEFAULT_DATABASE_URL — a
# real deployment MUST set JWT_SECRET, or every restart invalidates every
# session and (worse) a shared default secret would let anyone forge tokens.
_DEFAULT_JWT_SECRET = 'mediapulse-local-dev-secret-do-not-use-in-production'
ACCESS_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days


def _jwt_secret() -> str:
    return os.environ.get('JWT_SECRET', _DEFAULT_JWT_SECRET)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(_PBKDF2_ALGO, password.encode('utf-8'), bytes.fromhex(salt), _PBKDF2_ITERATIONS)
    return f'pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${digest.hex()}'


def verify_password(password: str, encoded: Optional[str]) -> bool:
    if not encoded:
        return False
    try:
        algo_tag, iterations_text, salt, expected_hex = encoded.split('$')
    except ValueError:
        return False
    if algo_tag != 'pbkdf2_sha256':
        return False
    digest = hashlib.pbkdf2_hmac(_PBKDF2_ALGO, password.encode('utf-8'), bytes.fromhex(salt), int(iterations_text))
    # Constant-time compare — a naive `==` here would let a timing attack
    # narrow down the correct hash one byte at a time.
    return hmac.compare_digest(digest.hex(), expected_hex)


@dataclass
class TokenClaims:
    user_id: str
    email: str
    role: str
    issued_at: int
    expires_at: int


def create_access_token(user_id: str, email: str, role: str) -> str:
    now = int(time.time())
    payload = {
        'sub': user_id,
        'email': email,
        'role': role,
        'iat': now,
        'exp': now + ACCESS_TOKEN_TTL_SECONDS,
    }
    return jwt.encode(payload, _jwt_secret(), algorithm='HS256')


class InvalidTokenError(Exception):
    pass


def decode_access_token(token: str) -> TokenClaims:
    try:
        payload = jwt.decode(token, _jwt_secret(), algorithms=['HS256'])
    except jwt.PyJWTError as error:
        raise InvalidTokenError(str(error)) from error
    return TokenClaims(
        user_id=payload['sub'],
        email=payload['email'],
        role=payload['role'],
        issued_at=payload['iat'],
        expires_at=payload['exp'],
    )
