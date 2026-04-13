"""Authentication router: register, login, and current user profile."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, ConfigDict, field_validator
from slowapi import Limiter
from slowapi.util import get_remote_address

from backend.app.models.response import APIResponse
from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

router = APIRouter(prefix="/auth", tags=["auth"])
logger = get_logger("api.auth")

_limiter = Limiter(key_func=get_remote_address)

_raw_secret = os.environ.get("AUTH_SECRET_KEY")
_debug_mode = os.environ.get("DEBUG", "false").lower() == "true"

if not _raw_secret:
    if _debug_mode:
        _raw_secret = secrets.token_urlsafe(32)
        logger.warning(
            "AUTH_SECRET_KEY env var not set — using ephemeral secret (DEBUG mode). "
            "All JWT tokens will be invalidated on restart. "
            "Set AUTH_SECRET_KEY in your environment for stable auth."
        )
    else:
        raise SystemExit(
            "FATAL: AUTH_SECRET_KEY environment variable must be set in production. "
            "Generate one with: openssl rand -hex 32"
        )

AUTH_SECRET_KEY: str = _raw_secret
AUTH_ALGORITHM = "HS256"
AUTH_TOKEN_EXPIRE_DAYS = 7

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


# ---------------------------------------------------------------------------
# Request / Response models (frozen)
# ---------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    """Body for POST /auth/register."""

    model_config = ConfigDict(frozen=True)

    email: str
    password: str
    display_name: str | None = None

    @field_validator("email")
    @classmethod
    def _validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("Invalid email format")
        return v

    @field_validator("password")
    @classmethod
    def _validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class LoginRequest(BaseModel):
    """Body for POST /auth/login."""

    model_config = ConfigDict(frozen=True)

    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _normalise_email(cls, v: str) -> str:
        return v.strip().lower()


class UserProfile(BaseModel):
    """Public user profile returned by the API."""

    model_config = ConfigDict(frozen=True)

    id: str
    email: str
    display_name: str | None = None
    created_at: str | None = None
    is_admin: bool = False  # Admin role — read from users.is_admin column


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hash_password(plain: str) -> str:
    return _pwd_ctx.hash(plain)


def _verify_password(plain: str, hashed: str) -> bool:
    return _pwd_ctx.verify(plain, hashed)


def _create_access_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=AUTH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, AUTH_SECRET_KEY, algorithm=AUTH_ALGORITHM)


def _decode_token(token: str) -> str:
    """Decode JWT and return the user_id (sub claim). Raises on failure."""
    try:
        payload = jwt.decode(token, AUTH_SECRET_KEY, algorithms=[AUTH_ALGORITHM])
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise JWTError("Missing sub claim")
        return user_id
    except JWTError as exc:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


_oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

# ---------------------------------------------------------------------------
# Dependency: get_current_user
# ---------------------------------------------------------------------------


async def get_current_user(
    token: Annotated[str, Depends(_oauth2_scheme)],
) -> UserProfile:
    """FastAPI dependency that extracts and validates the current user from JWT.

    Usage in other routers::

        from backend.app.api.auth import get_current_user
        from backend.app.api.auth import UserProfile

        @router.get("/protected")
        async def protected(user: UserProfile = Depends(get_current_user)):
            ...
    """
    user_id = _decode_token(token)
    try:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT id, email, display_name, created_at, is_admin FROM users WHERE id = ?",
                (user_id,),
            )
            row = await cursor.fetchone()
    except Exception as exc:
        logger.exception("DB error fetching user %s", user_id)
        raise HTTPException(status_code=500, detail="Database error") from exc

    if row is None:
        raise HTTPException(
            status_code=401,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return UserProfile(
        id=row["id"],
        email=row["email"],
        display_name=row["display_name"],
        created_at=row["created_at"],
        is_admin=bool(row["is_admin"]) if row["is_admin"] is not None else False,
    )


async def get_optional_user(
    token: Annotated[str | None, Depends(_oauth2_scheme_optional)],
) -> UserProfile | None:
    """Optional auth dependency — returns None when no token is provided.

    Use this on endpoints that work both authenticated and unauthenticated::

        from backend.app.api.auth import get_optional_user, UserProfile

        @router.post("/create")
        async def create(user: UserProfile | None = Depends(get_optional_user)):
            owner_id = user.id if user else None
    """
    if not token:
        return None
    try:
        user_id = _decode_token(token)
    except HTTPException:
        return None
    try:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT id, email, display_name, created_at, is_admin FROM users WHERE id = ?",
                (user_id,),
            )
            row = await cursor.fetchone()
    except Exception:
        logger.warning("DB error in get_optional_user for user %s", user_id)
        return None
    if row is None:
        return None
    return UserProfile(
        id=row["id"],
        email=row["email"],
        display_name=row["display_name"],
        created_at=row["created_at"],
        is_admin=bool(row["is_admin"]) if row["is_admin"] is not None else False,
    )


# ---------------------------------------------------------------------------
# Admin dependency
# ---------------------------------------------------------------------------


async def require_admin(
    user: Annotated[UserProfile, Depends(get_current_user)],
) -> UserProfile:
    """Reject non-admin users with 403.

    Usage in other routers::

        from backend.app.api.auth import require_admin, UserProfile

        @router.get("/admin/data")
        async def admin_data(user: UserProfile = Depends(require_admin)):
            ...
    """
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/register", response_model=APIResponse)
@_limiter.limit("3/minute")
async def register(request: Request, req: RegisterRequest) -> APIResponse:
    """Create a new user account.

    Returns 409 if the email is already registered.
    """
    user_id = uuid.uuid4().hex
    password_hash = _hash_password(req.password)
    display_name = req.display_name or req.email.split("@")[0]

    try:
        async with get_db() as db:
            # Check for duplicate email
            cursor = await db.execute("SELECT id FROM users WHERE email = ?", (req.email,))
            existing = await cursor.fetchone()
            if existing is not None:
                raise HTTPException(status_code=409, detail="Email already registered")

            await db.execute(
                "INSERT INTO users (id, email, password_hash, display_name) VALUES (?, ?, ?, ?)",
                (user_id, req.email, password_hash, display_name),
            )
            await db.commit()
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("register failed for %s", req.email)
        raise HTTPException(status_code=500, detail="Registration failed") from exc

    token = _create_access_token(user_id)
    logger.info("User registered: %s (%s)", user_id, req.email)
    return APIResponse(
        success=True,
        data={
            "user_id": user_id,
            "email": req.email,
            "display_name": display_name,
            "token": token,
        },
    )


@router.post("/login", response_model=APIResponse)
@_limiter.limit("5/minute")
async def login(request: Request, req: LoginRequest) -> APIResponse:
    """Authenticate with email + password, return JWT token.

    Returns 401 for invalid credentials.
    """
    try:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT id, email, password_hash, display_name FROM users WHERE email = ?",
                (req.email,),
            )
            row = await cursor.fetchone()
    except Exception as exc:
        logger.exception("login DB error for %s", req.email)
        raise HTTPException(status_code=500, detail="Login failed") from exc

    if row is None or not _verify_password(req.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = _create_access_token(row["id"])
    logger.info("User logged in: %s", row["id"])
    return APIResponse(
        success=True,
        data={
            "user_id": row["id"],
            "email": row["email"],
            "display_name": row["display_name"],
            "token": token,
        },
    )


@router.get("/me", response_model=APIResponse)
async def get_me(
    user: Annotated[UserProfile, Depends(get_current_user)],
) -> APIResponse:
    """Return the current authenticated user's profile."""
    return APIResponse(
        success=True,
        data={
            "user_id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "created_at": user.created_at,
        },
    )
