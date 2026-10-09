from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional

from app.database import get_db
from app.models.models import User
from app.schemas.schemas import UserOut
from app.core.security import get_current_user

router = APIRouter(prefix="/api/users", tags=["User Profile"])


class ProfileUpdate(BaseModel):
    full_name: Optional[str] = Field(None, min_length=2, max_length=120)
    phone: Optional[str] = None
    company_name: Optional[str] = None


@router.put("/me", response_model=UserOut, summary="Update my profile")
def update_profile(payload: ProfileUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if payload.full_name is not None:
        current_user.full_name = payload.full_name
    if payload.phone is not None:
        current_user.phone = payload.phone
    if payload.company_name is not None:
        current_user.company_name = payload.company_name
    db.commit()
    db.refresh(current_user)
    return current_user
