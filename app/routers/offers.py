"""
Home-page offers.

  GET    /api/offers                 public — active, not expired (filter ?category=flights)
  GET    /api/offers/categories      public — categories that currently have offers
  GET    /api/offers/admin           admin  — everything
  POST   /api/offers                 admin  — create
  PUT    /api/offers/{id}            admin  — edit / enable / disable
  DELETE /api/offers/{id}            admin  — delete
"""
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.security import get_current_user, require_roles
from app.services.activity import audit
from app.models.models import User
from app.database import SessionLocal, get_db
from app.models.models import Offer, UserRole

router = APIRouter(prefix="/api/offers", tags=["Offers"])

CATEGORIES = ["flights", "hotels", "holidays", "bank", "trains", "bus", "cabs", "forex", "visa"]


class OfferIn(BaseModel):
    category: str = Field(..., examples=["flights"])
    tag: Optional[str] = Field(None, max_length=40, examples=["DOM FLIGHTS"])
    title: str = Field(..., min_length=3, max_length=160)
    description: Optional[str] = Field(None, max_length=300)
    image_url: Optional[str] = Field(None, max_length=500)
    badge: Optional[str] = Field(None, max_length=60)
    promo_code: Optional[str] = Field(None, max_length=30)
    cta_label: Optional[str] = Field("Book now", max_length=30)
    cta_link: Optional[str] = Field("/flights", max_length=300)
    terms: Optional[str] = None
    valid_till: Optional[date] = None
    is_active: bool = True
    sort_order: int = 0


class OfferOut(BaseModel):
    id: int
    category: str
    tag: Optional[str] = None
    title: str
    description: Optional[str] = None
    image_url: Optional[str] = None
    badge: Optional[str] = None
    promo_code: Optional[str] = None
    cta_label: Optional[str] = None
    cta_link: Optional[str] = None
    terms: Optional[str] = None
    valid_till: Optional[str] = None
    is_active: bool
    sort_order: int
    created_at: datetime

    class Config:
        from_attributes = True


def _apply(o: Offer, data: OfferIn):
    if data.category not in CATEGORIES:
        raise HTTPException(status_code=422, detail=f"Category must be one of: {', '.join(CATEGORIES)}")
    for k, v in data.model_dump().items():
        if k == "valid_till":
            v = v.isoformat() if v else None
        if k == "promo_code" and v:
            v = v.strip().upper()
        setattr(o, k, v)


@router.get("", response_model=List[OfferOut], summary="Active offers for the website")
def list_offers(category: Optional[str] = Query(None), db: Session = Depends(get_db)):
    today = date.today().isoformat()
    q = db.query(Offer).filter(Offer.is_active == True)  # noqa: E712
    q = q.filter(or_(Offer.valid_till.is_(None), Offer.valid_till == "", Offer.valid_till >= today))
    if category and category != "all":
        q = q.filter(Offer.category == category)
    return q.order_by(Offer.sort_order.asc(), Offer.created_at.desc()).all()


@router.get("/categories", summary="Categories that have live offers")
def offer_categories(db: Session = Depends(get_db)):
    present = {c for (c,) in db.query(Offer.category).filter(Offer.is_active == True).distinct()}  # noqa: E712
    return [c for c in CATEGORIES if c in present]


@router.get("/admin", response_model=List[OfferOut], summary="All offers (Admin)",
            dependencies=[Depends(require_roles(UserRole.ADMIN, UserRole.SUPER_ADMIN))])
def admin_list_offers(db: Session = Depends(get_db)):
    return db.query(Offer).order_by(Offer.sort_order.asc(), Offer.created_at.desc()).all()


@router.post("", response_model=OfferOut, status_code=201, summary="Create offer (Admin)",
             dependencies=[Depends(require_roles(UserRole.ADMIN, UserRole.SUPER_ADMIN))])
def create_offer(payload: OfferIn, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    o = Offer()
    _apply(o, payload)
    db.add(o)
    db.commit()
    db.refresh(o)
    audit(db, me, "offer.created", f"Offer #{o.id}", o.title)
    return o


@router.put("/{offer_id}", response_model=OfferOut, summary="Edit offer (Admin)",
            dependencies=[Depends(require_roles(UserRole.ADMIN, UserRole.SUPER_ADMIN))])
def update_offer(offer_id: int, payload: OfferIn, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    o = db.query(Offer).filter(Offer.id == offer_id).first()
    if not o:
        raise HTTPException(status_code=404, detail="Offer not found.")
    _apply(o, payload)
    db.commit()
    db.refresh(o)
    audit(db, me, "offer.updated", f"Offer #{o.id}", f"{o.title} · {'live' if o.is_active else 'hidden'}")
    return o


@router.delete("/{offer_id}", status_code=204, summary="Delete offer (Admin)",
               dependencies=[Depends(require_roles(UserRole.ADMIN, UserRole.SUPER_ADMIN))])
def delete_offer(offer_id: int, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    o = db.query(Offer).filter(Offer.id == offer_id).first()
    if not o:
        raise HTTPException(status_code=404, detail="Offer not found.")
    title = o.title
    db.delete(o)
    db.commit()
    audit(db, me, "offer.deleted", f"Offer #{offer_id}", title)


# Sample offers so the home page isn't empty on first run. Only inserted when the
# offers table is completely empty — edit or delete them from Admin → Offers.
SAMPLE_OFFERS = [
    dict(category="flights", tag="DOM FLIGHTS", title="Flat ₹1,200 OFF on domestic flights",
         description="On bookings above ₹4,999. Valid on all airlines.", promo_code="FLYSMT",
         cta_label="Book now", cta_link="/flights", image_url="https://picsum.photos/seed/smt-offer-dom/400/300", sort_order=1),
    dict(category="flights", tag="INTL FLIGHTS", title="Up to 12% OFF on international flights",
         description="Dubai, Singapore, Bangkok and more — save big on your next trip.", promo_code="WORLDSMT",
         cta_label="View details", cta_link="/flights", image_url="https://picsum.photos/seed/smt-offer-intl/400/300", sort_order=2),
    dict(category="hotels", tag="DOM HOTELS", title="Up to 25% OFF on 4★ & 5★ hotels",
         description="Weekend stays across Goa, Jaipur, Udaipur and Manali.", promo_code="STAYSMT",
         cta_label="Book now", cta_link="/hotels", image_url="https://picsum.photos/seed/smt-offer-hotel/400/300", sort_order=3),
    dict(category="hotels", tag="INTL HOTELS", title="Flat 15% OFF on international hotels",
         description="Book a comfy stay in Dubai, Bangkok or Bali with big savings.", promo_code="INTLSTAY",
         cta_label="View details", cta_link="/hotels", image_url="https://picsum.photos/seed/smt-offer-intlhotel/400/300", sort_order=4),
    dict(category="bank", tag="BANK OFFER", title="Extra 10% OFF with credit cards",
         description="Instant discount on flights & hotels with select bank credit cards.", badge="Bank offer",
         cta_label="View details", cta_link="/flights", image_url="https://picsum.photos/seed/smt-offer-bank/400/300", sort_order=5),
    dict(category="holidays", tag="HOLIDAYS", title="Kerala & Goa packages — free night stay",
         description="On 5N+ holiday packages. Limited period.", promo_code="HOLISMT",
         cta_label="Explore", cta_link="/packages", image_url="https://picsum.photos/seed/smt-offer-holiday/400/300", sort_order=6),
    dict(category="holidays", tag="UMRAH", title="All-inclusive Umrah packages",
         description="Flights, hotel near Haram, visa and transfers included.",
         cta_label="Enquire now", cta_link="/hajj-umrah", image_url="https://picsum.photos/seed/smt-offer-umrah/400/300", sort_order=7),
    dict(category="visa", tag="VISA", title="Dubai visa in 48 hours",
         description="Hassle-free e-visa processing with document support.",
         cta_label="Apply now", cta_link="/visa", image_url="https://picsum.photos/seed/smt-offer-visa/400/300", sort_order=8),
    dict(category="bus", tag="BUS", title="Flat ₹150 OFF on bus tickets",
         description="On your first bus booking with SaSmyTrip.", promo_code="BUSSMT",
         cta_label="Book now", cta_link="/buses", image_url="https://picsum.photos/seed/smt-offer-bus/400/300", sort_order=9),
    dict(category="forex", tag="FOREX", title="Zero markup on forex cards",
         description="Best exchange rates for your international trip.",
         cta_label="View details", cta_link="/money-exchange", image_url="https://picsum.photos/seed/smt-offer-forex/400/300", sort_order=10),
]


def seed_offers():
    db = SessionLocal()
    try:
        if db.query(Offer).count() == 0:
            for row in SAMPLE_OFFERS:
                db.add(Offer(terms="T&C apply. Offer can be changed or withdrawn anytime.", is_active=True, **row))
            db.commit()
    finally:
        db.close()
