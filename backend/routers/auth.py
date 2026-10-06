import re

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import User
from backend.schemas import UserCreate, UserResponse
from backend.security import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    REFRESH_TOKEN_EXPIRE_DAYS,
    RateLimitExceeded,
    consume_refresh_token,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    enforce_rate_limit,
    hash_password,
    revoke_token,
    validate_password,
    verify_password,
)


router = APIRouter(prefix="/auth", tags=["Authentication"])
bearer_scheme = HTTPBearer(auto_error=False)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str | None = Field(default=None, min_length=1)


class AuthTokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_expires_in: int


def _client_key(request: Request) -> str:
    if request.client is None or not request.client.host:
        return "unknown"
    return request.client.host


def _rate_limit_or_429(key: str, *, limit: int, window_seconds: int) -> None:
    try:
        enforce_rate_limit(key, limit=limit, window_seconds=window_seconds)
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc


def _normalize_email(raw_email: str) -> str:
    email = raw_email.strip().lower()
    if len(email) > 320 or not _EMAIL_RE.fullmatch(email):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A valid email address is required.",
        )
    return email


def _auth_error(detail: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _issue_token_pair(user_id: int) -> AuthTokenResponse:
    return AuthTokenResponse(
        access_token=create_access_token(str(user_id)),
        refresh_token=create_refresh_token(str(user_id)),
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        refresh_expires_in=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
    )


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(
    user_data: UserCreate,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    _rate_limit_or_429(
        f"register:{_client_key(request)}",
        limit=8,
        window_seconds=60,
    )

    email = _normalize_email(user_data.email)
    try:
        validate_password(user_data.password)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    existing_user = db.scalar(select(User).where(User.email == email))
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    try:
        password_hash = hash_password(user_data.password)
        user = User(email=email, password_hash=password_hash)
        db.add(user)
        db.commit()
        db.refresh(user)
    except Exception:
        db.rollback()
        raise

    response.headers["Cache-Control"] = "no-store"
    return user


@router.post("/login", response_model=AuthTokenResponse)
def login(
    login_data: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    client_key = _client_key(request)
    _rate_limit_or_429(
        f"login-ip:{client_key}",
        limit=10,
        window_seconds=60,
    )

    email = _normalize_email(login_data.email)
    _rate_limit_or_429(
        f"login-email:{email}",
        limit=5,
        window_seconds=60,
    )

    user = db.scalar(select(User).where(User.email == email))

    password_matches = False
    if user is not None:
        password_matches = verify_password(login_data.password, user.password_hash)

    if not password_matches:
        _auth_error("Invalid email or password.")

    response.headers["Cache-Control"] = "no-store"
    return _issue_token_pair(user.id)


@router.post("/refresh", response_model=AuthTokenResponse)
def refresh(
    refresh_data: RefreshRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    _rate_limit_or_429(
        f"refresh:{_client_key(request)}",
        limit=10,
        window_seconds=60,
    )

    if not refresh_data.refresh_token:
        _auth_error("Refresh token is required.")

    try:
        payload = decode_refresh_token(refresh_data.refresh_token)
        jti = payload["jti"]
        exp = float(payload["exp"])
        user_id = int(payload["sub"])
    except (jwt.InvalidTokenError, TypeError, ValueError, KeyError):
        _auth_error("Invalid or expired refresh token.")

    if not consume_refresh_token(jti, exp):
        _auth_error("Refresh token has already been used or revoked.")

    user = db.get(User, user_id)
    if user is None:
        _auth_error("User no longer exists.")

    response.headers["Cache-Control"] = "no-store"
    return _issue_token_pair(user.id)


@router.post("/logout")
def logout(
    refresh_data: RefreshRequest | None = None,
    request: Request | None = None,
    response: Response | None = None,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
):
    if request is not None:
        _rate_limit_or_429(
            f"logout:{_client_key(request)}",
            limit=20,
            window_seconds=60,
        )

    revoked_any = False

    if credentials is not None:
        try:
            payload = decode_access_token(credentials.credentials)
            revoke_token(payload["jti"], float(payload["exp"]))
            revoked_any = True
        except (jwt.InvalidTokenError, TypeError, ValueError, KeyError):
            pass

    if refresh_data is not None and refresh_data.refresh_token:
        try:
            payload = decode_refresh_token(refresh_data.refresh_token)
            revoke_token(payload["jti"], float(payload["exp"]))
            revoked_any = True
        except (jwt.InvalidTokenError, TypeError, ValueError, KeyError):
            pass

    if not revoked_any:
        _auth_error("A valid access or refresh token is required.")

    if response is not None:
        response.headers["Cache-Control"] = "no-store"

    return {"message": "Logged out successfully."}


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        _auth_error("Authentication required.")

    try:
        payload = decode_access_token(credentials.credentials)
        subject = payload.get("sub")
        user_id = int(subject)
    except (jwt.InvalidTokenError, TypeError, ValueError):
        _auth_error("Invalid or expired token.")

    user = db.get(User, user_id)
    if user is None:
        _auth_error("User no longer exists.")

    return user


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user
