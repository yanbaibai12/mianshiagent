import base64
import hashlib
import hmac
import json
import time
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.dependencies import get_db
from app.models import User

security = HTTPBearer()
settings = get_settings()


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _sign(payload: str) -> str:
    digest = hmac.new(settings.SECRET_KEY.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
    return _b64encode(digest)


def create_access_token(user_id: str) -> str:
    now = int(time.time())
    expires_at = now + settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    payload = _b64encode(
        json.dumps(
            {"sub": user_id, "type": "access", "iat": now, "exp": expires_at},
            separators=(",", ":"),
        ).encode("utf-8")
    )
    return f"{payload}.{_sign(payload)}"


def _decode_access_token(token: str) -> UUID:
    try:
        payload, signature = token.split(".", 1)
        if not hmac.compare_digest(_sign(payload), signature):
            raise ValueError("invalid signature")
        data = json.loads(_b64decode(payload).decode("utf-8"))
        if data.get("type") != "access":
            raise ValueError("invalid token type")
        if int(data.get("exp", 0)) < int(time.time()):
            raise ValueError("token expired")
        return UUID(str(data["sub"]))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的认证凭证") from exc


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    user_id = _decode_access_token(credentials.credentials)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")

    return user


def is_admin_user(user: User) -> bool:
    admin_emails = set(settings.admin_email_list)
    return bool(admin_emails) and user.email.lower() in admin_emails


async def require_admin_user(current_user: User = Depends(get_current_user)) -> User:
    if not is_admin_user(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return current_user
