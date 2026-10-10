"""
Home-page image carousels, managed from Admin → Home sections.

  GET    /api/home-cards                  public — active cards grouped by section
  GET    /api/home-cards/admin            admin  — all cards
  POST   /api/home-cards                  admin
  PUT    /api/home-cards/{id}             admin
  DELETE /api/home-cards/{id}             admin
"""
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import get_current_user, require_roles
from app.services.activity import audit
from app.models.models import User
from app.database import SessionLocal, get_db
from app.models.models import HomeCard, UserRole

router = APIRouter(prefix="/api/home-cards", tags=["Home page content"])

# section key -> heading shown on the home page
SECTIONS = {
    "airlines": "Fly with India's favourite airlines",
    "hotel_collections": "Stays for every kind of trip",
    "collections": "Handpicked Collections for You",
    "wonders": "Unlock Lesser-Known Wonders of India",
}


class CardIn(BaseModel):
    section: str
    title: str = Field(..., min_length=2, max_length=160)
    subtitle: Optional[str] = Field(None, max_length=200)
    badge: Optional[str] = Field(None, max_length=30)
    image_url: Optional[str] = Field(None, max_length=500)
    link: Optional[str] = Field(None, max_length=300)
    is_active: bool = True
    sort_order: int = 0


class CardOut(CardIn):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


def _check(section: str):
    if section not in SECTIONS:
        raise HTTPException(status_code=422, detail=f"Section must be one of: {', '.join(SECTIONS)}")


@router.get("", summary="Home-page carousels (public)")
def public_cards(db: Session = Depends(get_db)) -> Dict:
    rows = (db.query(HomeCard).filter(HomeCard.is_active == True)  # noqa: E712
            .order_by(HomeCard.sort_order.asc(), HomeCard.id.asc()).all())
    out = {k: {"title": v, "cards": []} for k, v in SECTIONS.items()}
    for r in rows:
        if r.section in out:
            out[r.section]["cards"].append(CardOut.model_validate(r).model_dump(mode="json"))
    return out


@router.get("/admin", response_model=List[CardOut], summary="All cards (Admin)",
            dependencies=[Depends(require_roles(UserRole.ADMIN, UserRole.SUPER_ADMIN))])
def admin_cards(db: Session = Depends(get_db)):
    return db.query(HomeCard).order_by(HomeCard.section, HomeCard.sort_order, HomeCard.id).all()


@router.post("", response_model=CardOut, status_code=201, summary="Add card (Admin)",
             dependencies=[Depends(require_roles(UserRole.ADMIN, UserRole.SUPER_ADMIN))])
def add_card(payload: CardIn, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    _check(payload.section)
    c = HomeCard(**payload.model_dump())
    db.add(c)
    db.commit()
    db.refresh(c)
    audit(db, me, "home_card.created", f"Card #{c.id}", f"{c.section} · {c.title}")
    return c


@router.put("/{card_id}", response_model=CardOut, summary="Edit card (Admin)",
            dependencies=[Depends(require_roles(UserRole.ADMIN, UserRole.SUPER_ADMIN))])
def edit_card(card_id: int, payload: CardIn, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    _check(payload.section)
    c = db.query(HomeCard).filter(HomeCard.id == card_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Card not found.")
    for k, v in payload.model_dump().items():
        setattr(c, k, v)
    db.commit()
    db.refresh(c)
    audit(db, me, "home_card.updated", f"Card #{c.id}", f"{c.section} · {c.title}")
    return c


@router.delete("/{card_id}", status_code=204, summary="Delete card (Admin)",
               dependencies=[Depends(require_roles(UserRole.ADMIN, UserRole.SUPER_ADMIN))])
def delete_card(card_id: int, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    c = db.query(HomeCard).filter(HomeCard.id == card_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Card not found.")
    title = c.title
    db.delete(c)
    db.commit()
    audit(db, me, "home_card.deleted", f"Card #{card_id}", title)


def _pic(seed):
    return f"https://picsum.photos/seed/{seed}/480/560"


def _hotels(city):
    return f"/hotels?q={city}"


SAMPLE = [
    # Airlines bookable through the flight search (no logos/claims of partnership — add your own artwork)
    ("airlines", "IndiGo", "Largest domestic network", None, "smt-air-6e", "/flights"),
    ("airlines", "Air India", "Domestic & international", None, "smt-air-ai", "/flights"),
    ("airlines", "Air India Express", "Value fares, Gulf routes", None, "smt-air-ix", "/flights"),
    ("airlines", "Akasa Air", "New-age domestic carrier", None, "smt-air-qp", "/flights"),
    ("airlines", "SpiceJet", "Budget domestic flights", None, "smt-air-sg", "/flights"),
    ("airlines", "Emirates", "Fly via Dubai", None, "smt-air-ek", "/flights"),
    # Hotel collections
    ("hotel_collections", "Luxury Resorts", "5★ pools, spas & sea views", None, "smt-hc-lux", _hotels("Goa")),
    ("hotel_collections", "Heritage Palaces", "Royal stays in Rajasthan", None, "smt-hc-heritage", _hotels("Udaipur")),
    ("hotel_collections", "Business Hotels", "Near airports & offices", None, "smt-hc-biz", _hotels("Bangalore")),
    ("hotel_collections", "Hill Retreats", "Cottages with mountain views", None, "smt-hc-hill", _hotels("Manali")),
    # Curated collections
    ("collections", "Stays in & around Delhi for a weekend getaway", None, "TOP 8", "smt-col-delhi", _hotels("New Delhi")),
    ("collections", "Stays in & around Mumbai for a weekend getaway", None, "TOP 8", "smt-col-mumbai", _hotels("Mumbai")),
    ("collections", "Stays in & around Bangalore for a weekend getaway", None, "TOP 9", "smt-col-blr", _hotels("Bangalore")),
    ("collections", "Beach destinations", None, "TOP 11", "smt-col-beach", _hotels("Goa")),
    ("collections", "Weekend getaways", None, "TOP 11", "smt-col-weekend", _hotels("Jaipur")),
    ("collections", "Hill stations", None, "TOP 11", "smt-col-hills", _hotels("Manali")),
    # Hidden gems
    ("wonders", "Chail — Shimla's best kept secret", None, None, "smt-w-chail", "/packages"),
    ("wonders", "Kolli Hills — Tamil Nadu's charming hill town", None, None, "smt-w-kolli", "/packages"),
    ("wonders", "Chakrata — picturesque gateway to the Himalayas", None, None, "smt-w-chakrata", "/packages"),
    ("wonders", "Saputara — quaint hill station in Gujarat", None, None, "smt-w-saputara", "/packages"),
    ("wonders", "Lachung — snowy winter wonderland", None, None, "smt-w-lachung", "/packages"),
    ("wonders", "Mandarmani — seaside escape in West Bengal", None, None, "smt-w-mandarmani", "/packages"),
]


def seed_home_cards():
    db = SessionLocal()
    try:
        if db.query(HomeCard).count() == 0:
            for i, (section, title, subtitle, badge, seed, link) in enumerate(SAMPLE):
                db.add(HomeCard(section=section, title=title, subtitle=subtitle, badge=badge,
                                image_url=_pic(seed), link=link, sort_order=i, is_active=True))
            db.commit()
    finally:
        db.close()
