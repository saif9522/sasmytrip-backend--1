"""
Service enquiries (leads) for services without a booking API yet:
trains, buses, cabs, cruise, hajj & umrah, travel insurance, forex, visa, holidays, activities.

  POST /api/enquiries                public (logged-in user is linked automatically)
  GET  /api/enquiries/my             customer — own enquiries
  GET  /api/enquiries/admin          admin — filter by ?service= & ?status=
  GET  /api/enquiries/admin/summary  admin — counts per status
  PUT  /api/enquiries/{id}           admin — update status / note
"""
import json
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.security import ALGORITHM, SECRET_KEY, get_current_user, require_roles
from app.database import get_db
from app.models.models import Enquiry, EnquiryStatus, Notification, User, UserRole

router = APIRouter(prefix="/api/enquiries", tags=["Enquiries (leads)"])

SERVICES = {
    "train": "Trains", "bus": "Buses", "cab": "Cabs", "cruise": "Cruise", "hajj_umrah": "Hajj & Umrah",
    "travel_insurance": "Travel Insurance", "money_exchange": "Money Exchange", "visa": "Visa",
    "package": "Holiday Packages", "activity": "Activities",
}


class EnquiryIn(BaseModel):
    service: str
    name: str = Field(..., min_length=2, max_length=120)
    phone: str = Field(..., min_length=7, max_length=20)
    email: Optional[EmailStr] = None
    details: Dict[str, str] = Field(default_factory=dict)
    message: Optional[str] = Field(None, max_length=2000)

    @field_validator("service")
    @classmethod
    def known_service(cls, v):
        if v not in SERVICES:
            raise ValueError(f"Unknown service. Use one of: {', '.join(SERVICES)}")
        return v

    @field_validator("phone")
    @classmethod
    def phone_digits(cls, v):
        digits = "".join(ch for ch in v if ch.isdigit())
        if len(digits) < 7:
            raise ValueError("Enter a valid phone number.")
        return v.strip()

    @field_validator("details")
    @classmethod
    def small_details(cls, v):
        if len(v) > 30:
            raise ValueError("Too many fields.")
        return {str(k)[:60]: str(val)[:300] for k, val in v.items() if str(val).strip()}


class EnquiryUpdate(BaseModel):
    status: EnquiryStatus
    admin_note: Optional[str] = Field(None, max_length=2000)


class EnquiryOut(BaseModel):
    id: int
    service: str
    service_label: str
    reference: str
    name: str
    email: Optional[str] = None
    phone: str
    details: Dict[str, str]
    message: Optional[str] = None
    status: EnquiryStatus
    admin_note: Optional[str] = None
    user_id: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    @classmethod
    def of(cls, e: Enquiry) -> "EnquiryOut":
        return cls(
            id=e.id, service=e.service, service_label=SERVICES.get(e.service, e.service),
            reference=f"ENQ{e.id:06d}", name=e.name, email=e.email, phone=e.phone,
            details=json.loads(e.details_json) if e.details_json else {}, message=e.message,
            status=e.status, admin_note=e.admin_note, user_id=e.user_id,
            created_at=e.created_at, updated_at=e.updated_at,
        )


def optional_user(authorization: Optional[str] = Header(None), db: Session = Depends(get_db)) -> Optional[User]:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    try:
        payload = jwt.decode(authorization.split(" ", 1)[1], SECRET_KEY, algorithms=[ALGORITHM])
        return db.query(User).filter(User.id == int(payload.get("sub"))).first()
    except (JWTError, TypeError, ValueError):
        return None


@router.post("", response_model=EnquiryOut, status_code=201, summary="Send an enquiry (public)")
def create_enquiry(payload: EnquiryIn, db: Session = Depends(get_db), user: Optional[User] = Depends(optional_user)):
    e = Enquiry(
        service=payload.service, user_id=user.id if user else None, name=payload.name.strip(),
        email=payload.email, phone=payload.phone, details_json=json.dumps(payload.details, ensure_ascii=False),
        message=payload.message, status=EnquiryStatus.NEW,
    )
    db.add(e)
    db.flush()
    label = SERVICES[payload.service]
    # Ping every admin in their in-app notifications
    for admin in db.query(User).filter(User.role.in_([UserRole.ADMIN, UserRole.SUPER_ADMIN]), User.is_active == True).all():  # noqa: E712
        db.add(Notification(user_id=admin.id, title=f"New {label} enquiry",
                            message=f"ENQ{e.id:06d} from {e.name} ({e.phone})"))
    if user:
        db.add(Notification(user_id=user.id, title="Enquiry received",
                            message=f"We got your {label} enquiry (ENQ{e.id:06d}). Our team will call you shortly."))
    db.commit()
    db.refresh(e)
    return EnquiryOut.of(e)


@router.get("/my", response_model=List[EnquiryOut], summary="My enquiries")
def my_enquiries(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(Enquiry).filter(Enquiry.user_id == user.id).order_by(Enquiry.created_at.desc()).all()
    return [EnquiryOut.of(e) for e in rows]


@router.get("/admin", response_model=List[EnquiryOut], summary="All enquiries (Admin)",
            dependencies=[Depends(require_roles(UserRole.ADMIN, UserRole.SUPER_ADMIN))])
def admin_enquiries(service: Optional[str] = Query(None), status: Optional[EnquiryStatus] = Query(None),
                    db: Session = Depends(get_db)):
    q = db.query(Enquiry)
    if service:
        q = q.filter(Enquiry.service == service)
    if status:
        q = q.filter(Enquiry.status == status)
    return [EnquiryOut.of(e) for e in q.order_by(Enquiry.created_at.desc()).limit(1000).all()]


@router.get("/admin/summary", summary="Enquiry counts by status (Admin)",
            dependencies=[Depends(require_roles(UserRole.ADMIN, UserRole.SUPER_ADMIN))])
def admin_summary(db: Session = Depends(get_db)):
    rows = db.query(Enquiry.status, func.count(Enquiry.id)).group_by(Enquiry.status).all()
    out = {s.value: 0 for s in EnquiryStatus}
    out.update({s.value: n for s, n in rows})
    return {"by_status": out, "services": SERVICES}


@router.put("/{enquiry_id}", response_model=EnquiryOut, summary="Update enquiry status / note (Admin)",
            dependencies=[Depends(require_roles(UserRole.ADMIN, UserRole.SUPER_ADMIN))])
def update_enquiry(enquiry_id: int, payload: EnquiryUpdate, db: Session = Depends(get_db)):
    e = db.query(Enquiry).filter(Enquiry.id == enquiry_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Enquiry not found.")
    changed = e.status != payload.status
    e.status = payload.status
    e.admin_note = payload.admin_note
    if changed and e.user_id:
        msg = {
            EnquiryStatus.CONTACTED: "Our travel expert has picked up your enquiry.",
            EnquiryStatus.CONVERTED: "Your booking is confirmed. Thank you for choosing SaSmyTrip!",
            EnquiryStatus.CLOSED: "Your enquiry has been closed. Reach out anytime if you need help.",
        }.get(payload.status)
        if msg:
            db.add(Notification(user_id=e.user_id, title=f"Enquiry ENQ{e.id:06d} updated", message=msg))
    db.commit()
    db.refresh(e)
    return EnquiryOut.of(e)
