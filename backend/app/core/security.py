from datetime import UTC, datetime, timedelta

from jose import jwt
from passlib.context import CryptContext

from app.core.config import settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash a plaintext password. The plaintext is never logged or stored."""
    return _pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Return True if the plaintext matches the stored hash."""
    return _pwd_context.verify(plain_password, hashed_password)


def create_access_token(
    subject: str, role: str, expires_delta: timedelta | None = None
) -> str:
    """Create a signed JWT carrying the user id (sub), role, and an expiry (exp)."""
    expire = datetime.now(UTC) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    claims = {"sub": subject, "role": role, "exp": int(expire.timestamp())}
    return jwt.encode(
        claims, settings.jwt_secret.get_secret_value(), algorithm=settings.jwt_algorithm
    )


def decode_access_token(token: str) -> dict:
    """Decode and validate a JWT. Raises jose.JWTError if invalid or expired."""
    return jwt.decode(
        token, settings.jwt_secret.get_secret_value(), algorithms=[settings.jwt_algorithm]
    )
