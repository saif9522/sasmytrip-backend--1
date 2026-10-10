import os
from datetime import datetime, timedelta
from typing import Optional

from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import User, UserRole

# In production, load SECRET_KEY from an environment variable / secrets manager.
# Never commit real secrets to source control.
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-only-secret-change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None or not user.is_active:
        raise credentials_exception
    # Keep the login session's "last seen" fresh (throttled) for online status & working hours
    try:
        from app.services.activity import touch
        touch(db, payload.get("sid"), user.id)
    except Exception:
        pass
    return user


def require_roles(*allowed_roles: UserRole):
    """Dependency factory — restricts an endpoint to specific user roles.
    Usage: Depends(require_roles(UserRole.AGENT, UserRole.DISTRIBUTOR))"""
    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action requires one of these roles: {[r.value for r in allowed_roles]}",
            )
        return current_user
    return dependency


def require_booker(current_user: User = Depends(get_current_user)) -> User:
    """Who can make flight / hotel / service bookings: Travellers, and Agents once an admin has approved them."""
    if current_user.role == UserRole.CUSTOMER:
        return current_user
    if current_user.role == UserRole.AGENT:
        if not current_user.is_verified:
            raise HTTPException(status_code=403, detail="Your agent account is awaiting admin approval. You can book once it's approved.")
        return current_user
    raise HTTPException(status_code=403, detail="Log in with a Traveller or Agent account to book.")
