from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models.models import Review, Listing, Booking, User, UserRole, BookingStatus
from app.schemas.schemas import ReviewCreate, ReviewOut
from app.core.security import get_current_user, require_roles

router = APIRouter(prefix="/api/reviews", tags=["Reviews"])


def _recalculate_listing_rating(db: Session, listing_id: int):
    avg_rating, count = (
        db.query(func.avg(Review.rating), func.count(Review.id))
        .filter(Review.listing_id == listing_id)
        .first()
    )
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if listing:
        listing.rating = round(float(avg_rating or 0), 1)
        listing.review_count = count or 0
        db.commit()


@router.get(
    "/listing/{listing_id}",
    response_model=List[ReviewOut],
    summary="Reviews for a listing (public)",
)
def get_listing_reviews(listing_id: int, db: Session = Depends(get_db)):
    reviews = (
        db.query(Review)
        .filter(Review.listing_id == listing_id)
        .order_by(Review.created_at.desc())
        .all()
    )
    out = []
    for r in reviews:
        item = ReviewOut.model_validate(r)
        item.customer_name = r.customer.full_name if r.customer else None
        out.append(item)
    return out


@router.post(
    "",
    response_model=ReviewOut,
    status_code=201,
    summary="Submit a review (Customer only, must have a confirmed/completed booking on this listing)",
    dependencies=[Depends(require_roles(UserRole.CUSTOMER))],
)
def create_review(
    payload: ReviewCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    listing = db.query(Listing).filter(Listing.id == payload.listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found.")

    has_booking = (
        db.query(Booking)
        .filter(
            Booking.customer_id == current_user.id,
            Booking.listing_id == payload.listing_id,
            Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.COMPLETED]),
        )
        .first()
    )
    if not has_booking:
        raise HTTPException(
            status_code=403,
            detail="You can only review listings you've booked and paid for.",
        )

    existing = (
        db.query(Review)
        .filter(Review.customer_id == current_user.id, Review.listing_id == payload.listing_id)
        .first()
    )
    if existing:
        existing.rating = payload.rating
        existing.comment = payload.comment
        db.commit()
        db.refresh(existing)
        _recalculate_listing_rating(db, payload.listing_id)
        result = ReviewOut.model_validate(existing)
        result.customer_name = current_user.full_name
        return result

    review = Review(
        customer_id=current_user.id,
        listing_id=payload.listing_id,
        booking_id=has_booking.id,
        rating=payload.rating,
        comment=payload.comment,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    _recalculate_listing_rating(db, payload.listing_id)

    result = ReviewOut.model_validate(review)
    result.customer_name = current_user.full_name
    return result
