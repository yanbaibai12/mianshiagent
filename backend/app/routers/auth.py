from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.schemas import TokenResponse, UserLoginRequest, UserRegisterRequest, UserResponse
from app.services.audit import log_audit_event
from app.services.auth_service import create_access_token, get_current_user
from app.services.tenancy import ensure_personal_organization
from app.utils.security import get_password_hash, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse)
async def register(
    req: UserRegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    email = req.email.strip().lower()
    result = await db.execute(select(User).where(User.email == email))
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="该邮箱已注册")

    user = User(
        email=email,
        password_hash=get_password_hash(req.password),
        nickname=req.nickname,
    )
    db.add(user)
    await db.flush()
    org = await ensure_personal_organization(db, user)
    log_audit_event(
        db,
        event_type="auth.register",
        resource_type="user",
        actor_user_id=user.id,
        target_user_id=user.id,
        organization_id=org.id,
        resource_id=str(user.id),
        request=request,
        metadata={"email": user.email, "organization_id": str(org.id)},
    )
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
async def login(
    req: UserLoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    email = req.email.strip().lower()
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=400, detail="邮箱或密码错误")

    token = create_access_token(str(user.id))
    log_audit_event(
        db,
        event_type="auth.login",
        resource_type="user",
        actor_user_id=user.id,
        target_user_id=user.id,
        resource_id=str(user.id),
        request=request,
        metadata={"email": user.email},
    )
    await db.commit()
    return TokenResponse(
        access_token=token,
        user=UserResponse.model_validate(user),
    )


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)
