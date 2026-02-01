"""
Authentication API routes.

Provides REST endpoints for user registration, login, token refresh,
and profile management with rate limiting.
"""

import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Request, status
from pydantic import BaseModel, Field, field_validator
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.auth.jwt_handler import JWTHandler, TokenPair, TokenExpiredError, TokenInvalidError
from src.auth.password import PasswordHandler
from src.auth.dependencies import (
    get_jwt_handler,
    get_token_payload,
    get_current_user,
    get_current_user_payload,
    SessionManager,
    TokenPayload,
)
from src.models.user import UserRepository, User
from src.security.audit import get_audit_logger, AuditEventType, AuditSeverity
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Rate limiter for auth endpoints
limiter = Limiter(key_func=get_remote_address)

# Router
router = APIRouter(prefix="/api/auth", tags=["authentication"])

# Password handler
password_handler = PasswordHandler()


# ==================== REQUEST/RESPONSE MODELS ====================


class RegisterRequest(BaseModel):
    """User registration request."""
    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator('username')
    @classmethod
    def validate_username(cls, v: str) -> str:
        if not re.match(r'^[a-zA-Z0-9_-]+$', v):
            raise ValueError('Username can only contain letters, numbers, underscores, and hyphens')
        return v.lower()

    @field_validator('email')
    @classmethod
    def validate_email(cls, v: str) -> str:
        # Basic email validation
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', v):
            raise ValueError('Invalid email address')
        return v.lower()

    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        # Password strength requirements
        if not any(c.isupper() for c in v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not any(c.islower() for c in v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not any(c.isdigit() for c in v):
            raise ValueError('Password must contain at least one digit')
        return v


class LoginRequest(BaseModel):
    """User login request."""
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    """Token refresh request."""
    refresh_token: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    """Token response."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseModel):
    """User profile response."""
    id: int
    username: str
    email: str
    is_admin: bool
    is_active: bool
    created_at: datetime
    last_login: Optional[datetime]


class UpdateProfileRequest(BaseModel):
    """Update user profile request."""
    email: Optional[str] = Field(None, max_length=255)
    current_password: Optional[str] = Field(None, max_length=128)
    new_password: Optional[str] = Field(None, min_length=8, max_length=128)

    @field_validator('email')
    @classmethod
    def validate_email(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', v):
            raise ValueError('Invalid email address')
        return v.lower()

    @field_validator('new_password')
    @classmethod
    def validate_new_password(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not any(c.isupper() for c in v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not any(c.islower() for c in v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not any(c.isdigit() for c in v):
            raise ValueError('Password must contain at least one digit')
        return v


class MessageResponse(BaseModel):
    """Simple message response."""
    message: str
    success: bool = True


# ==================== AUTH ENDPOINTS ====================


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/hour")
async def register(
    request: Request,
    data: RegisterRequest,
    jwt_handler: JWTHandler = Depends(get_jwt_handler),
):
    """
    Register a new user account.

    Rate limited to 5 registrations per hour per IP.
    """
    user_repo = UserRepository()

    # Check if username or email already exists
    existing = await user_repo.get_by_username(data.username)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already registered"
        )

    existing = await user_repo.get_by_email(data.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered"
        )

    # Hash password and create user
    password_hash = password_handler.hash(data.password)
    user = await user_repo.create(
        username=data.username,
        email=data.email,
        password_hash=password_hash
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create user"
        )

    # Create token pair
    tokens = jwt_handler.create_token_pair(
        user_id=user.id,
        username=user.username,
        is_admin=user.is_admin
    )

    # Create session
    session_manager = SessionManager()
    await session_manager.create_session(
        user_id=user.id,
        access_token_hash=jwt_handler.hash_token(tokens.access_token),
        refresh_token_hash=jwt_handler.hash_token(tokens.refresh_token),
        expires_at=datetime.now(timezone.utc),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    logger.info(f"New user registered: {user.username} (ID: {user.id})")

    # Audit log registration
    audit = await get_audit_logger()
    await audit.log_auth_event(
        event_type=AuditEventType.USER_REGISTER,
        user_id=user.id,
        ip_address=request.client.host if request.client else None,
        username=user.username,
        success=True,
    )

    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        token_type=tokens.token_type,
        expires_in=tokens.expires_in
    )


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(
    request: Request,
    data: LoginRequest,
    jwt_handler: JWTHandler = Depends(get_jwt_handler),
):
    """
    Authenticate user and return tokens.

    Rate limited to 10 attempts per minute per IP.
    """
    user_repo = UserRepository()

    # Get user by username
    user = await user_repo.get_by_username(data.username)
    ip_address = request.client.host if request.client else None

    if not user:
        # Log failed login attempt
        audit = await get_audit_logger()
        await audit.log_auth_event(
            event_type=AuditEventType.USER_LOGIN_FAILED,
            user_id=None,
            ip_address=ip_address,
            username=data.username,
            success=False,
            error_message="Invalid username",
        )
        # Use same error message to prevent username enumeration
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password"
        )

    # Check if account is active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled"
        )

    # Verify password
    if not password_handler.verify(data.password, user.password_hash):
        logger.warning(f"Failed login attempt for user: {data.username}")
        # Log failed login
        audit = await get_audit_logger()
        await audit.log_auth_event(
            event_type=AuditEventType.USER_LOGIN_FAILED,
            user_id=user.id,
            ip_address=ip_address,
            username=data.username,
            success=False,
            error_message="Invalid password",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password"
        )

    # Update last login
    await user_repo.update_last_login(user.id)

    # Check if password needs rehash (work factor increased)
    if password_handler.needs_rehash(user.password_hash):
        new_hash = password_handler.hash(data.password)
        await user_repo.update_password(user.id, new_hash)
        logger.info(f"Password rehashed for user: {data.username}")

    # Create token pair
    tokens = jwt_handler.create_token_pair(
        user_id=user.id,
        username=user.username,
        is_admin=user.is_admin
    )

    # Create session
    session_manager = SessionManager()
    await session_manager.create_session(
        user_id=user.id,
        access_token_hash=jwt_handler.hash_token(tokens.access_token),
        refresh_token_hash=jwt_handler.hash_token(tokens.refresh_token),
        expires_at=datetime.now(timezone.utc),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    logger.info(f"User logged in: {data.username}")

    # Log successful login
    audit = await get_audit_logger()
    await audit.log_auth_event(
        event_type=AuditEventType.USER_LOGIN,
        user_id=user.id,
        ip_address=ip_address,
        username=data.username,
        success=True,
    )

    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        token_type=tokens.token_type,
        expires_in=tokens.expires_in
    )


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("30/minute")
async def refresh_token(
    request: Request,
    data: RefreshRequest,
    jwt_handler: JWTHandler = Depends(get_jwt_handler),
):
    """
    Refresh access token using refresh token.

    Rate limited to 30 requests per minute per IP.
    """
    try:
        # Verify refresh token and get new tokens
        new_tokens = jwt_handler.refresh_access_token(data.refresh_token)

        # Get payload for session tracking
        payload = jwt_handler.verify_refresh_token(data.refresh_token)

        # Revoke old session
        session_manager = SessionManager()
        old_hash = jwt_handler.hash_token(data.refresh_token)
        await session_manager.revoke_session(old_hash)

        # Create new session
        await session_manager.create_session(
            user_id=payload.user_id,
            access_token_hash=jwt_handler.hash_token(new_tokens.access_token),
            refresh_token_hash=jwt_handler.hash_token(new_tokens.refresh_token),
            expires_at=datetime.now(timezone.utc),
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )

        return TokenResponse(
            access_token=new_tokens.access_token,
            refresh_token=new_tokens.refresh_token,
            token_type=new_tokens.token_type,
            expires_in=new_tokens.expires_in
        )

    except TokenExpiredError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except TokenInvalidError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.post("/logout", response_model=MessageResponse)
@limiter.limit("30/minute")
async def logout(
    request: Request,
    payload: TokenPayload = Depends(get_token_payload),
    jwt_handler: JWTHandler = Depends(get_jwt_handler),
):
    """
    Logout current session (invalidate token).
    """
    # Get token from header
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        token_hash = jwt_handler.hash_token(token)

        # Revoke session
        session_manager = SessionManager()
        await session_manager.revoke_session(token_hash)

    logger.info(f"User logged out: {payload.username}")

    # Log logout
    audit = await get_audit_logger()
    await audit.log_auth_event(
        event_type=AuditEventType.USER_LOGOUT,
        user_id=payload.user_id,
        ip_address=request.client.host if request.client else None,
        username=payload.username,
        success=True,
    )

    return MessageResponse(message="Successfully logged out")


@router.get("/me", response_model=UserResponse)
@limiter.limit("60/minute")
async def get_current_user_profile(
    request: Request,
    payload: TokenPayload = Depends(get_current_user_payload),
):
    """
    Get current user's profile.
    """
    user_repo = UserRepository()
    user = await user_repo.get_by_id(payload.user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        is_admin=user.is_admin,
        is_active=user.is_active,
        created_at=user.created_at,
        last_login=user.last_login
    )


@router.put("/me", response_model=UserResponse)
@limiter.limit("10/minute")
async def update_current_user_profile(
    request: Request,
    data: UpdateProfileRequest,
    payload: TokenPayload = Depends(get_current_user_payload),
):
    """
    Update current user's profile.
    """
    user_repo = UserRepository()
    user = await user_repo.get_by_id(payload.user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Update email if provided
    if data.email and data.email != user.email:
        existing = await user_repo.get_by_email(data.email)
        if existing and existing.id != user.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already in use"
            )
        await user_repo.update_email(user.id, data.email)

    # Update password if provided
    if data.new_password:
        if not data.current_password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password required to change password"
            )

        if not password_handler.verify(data.current_password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Current password is incorrect"
            )

        new_hash = password_handler.hash(data.new_password)
        await user_repo.update_password(user.id, new_hash)
        logger.info(f"Password updated for user: {user.username}")

    # Fetch updated user
    updated_user = await user_repo.get_by_id(payload.user_id)

    return UserResponse(
        id=updated_user.id,
        username=updated_user.username,
        email=updated_user.email,
        is_admin=updated_user.is_admin,
        is_active=updated_user.is_active,
        created_at=updated_user.created_at,
        last_login=updated_user.last_login
    )
