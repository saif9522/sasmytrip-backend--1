from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models.models import User, Listing, Booking, UserRole, BookingStatus, Review, PaymentStatus, ListingType
from app.schemas.schemas import (
    DashboardStats, AdminUserOut, UpdateUserStatus, CreateAdminRequest,
    UserOut, ListingOut, ListingCreate, BookingOut, TokenResponse, ReviewOut, PaymentTransactionOut,
)
from app.core.security import get_current_user, require_roles, hash_password, create_access_token
from app.services.activity import audit

router = APIRouter(prefix="/api/admin", tags=["Admin"])

# Both Admin and Super Admin can view/moderate. Only Super Admin manages Admin accounts.
admin_or_super = require_roles(UserRole.ADMIN, UserRole.SUPER_ADMIN)
super_admin_only = require_roles(UserRole.SUPER_ADMIN)


@router.get(
    "/dashboard",
    response_model=DashboardStats,
    summary="Platform-wide overview stats",
    dependencies=[Depends(admin_or_super)],
)
def dashboard_stats(db: Session = Depends(get_db)):
    total_users = db.query(func.count(User.id)).scalar()
    total_customers = db.query(func.count(User.id)).filter(User.role == UserRole.CUSTOMER).scalar()
    total_agents = db.query(func.count(User.id)).filter(User.role == UserRole.AGENT).scalar()
    total_distributors = db.query(func.count(User.id)).filter(User.role == UserRole.DISTRIBUTOR).scalar()
    pending_verifications = (
        db.query(func.count(User.id))
        .filter(User.role.in_([UserRole.AGENT, UserRole.DISTRIBUTOR]), User.is_verified == False)  # noqa: E712
        .scalar()
    )
    total_listings = db.query(func.count(Listing.id)).scalar()
    active_listings = db.query(func.count(Listing.id)).filter(Listing.is_active == True).scalar()  # noqa: E712
    total_bookings = db.query(func.count(Booking.id)).scalar()
    pending_bookings = db.query(func.count(Booking.id)).filter(Booking.status == BookingStatus.PENDING).scalar()
    confirmed_bookings = db.query(func.count(Booking.id)).filter(Booking.status == BookingStatus.CONFIRMED).scalar()
    cancelled_bookings = db.query(func.count(Booking.id)).filter(Booking.status == BookingStatus.CANCELLED).scalar()
    completed_bookings = db.query(func.count(Booking.id)).filter(Booking.status == BookingStatus.COMPLETED).scalar()
    total_revenue = (
        db.query(func.coalesce(func.sum(Booking.total_amount), 0.0))
        .filter(Booking.status != BookingStatus.CANCELLED)
        .scalar()
    )
    paid_revenue = (
        db.query(func.coalesce(func.sum(Booking.total_amount), 0.0))
        .filter(Booking.payment_status == "paid")
        .scalar()
    )
    failed_payments = db.query(func.count(Booking.id)).filter(Booking.payment_status == "failed").scalar()

    return DashboardStats(
        total_users=total_users,
        total_customers=total_customers,
        total_agents=total_agents,
        total_distributors=total_distributors,
        pending_verifications=pending_verifications,
        total_listings=total_listings,
        active_listings=active_listings,
        total_bookings=total_bookings,
        pending_bookings=pending_bookings,
        confirmed_bookings=confirmed_bookings,
        cancelled_bookings=cancelled_bookings,
        completed_bookings=completed_bookings,
        total_revenue=float(total_revenue),
        paid_revenue=float(paid_revenue),
        failed_payments=failed_payments,
    )


@router.get(
    "/dashboard/listings-by-type",
    summary="Listing count per category — powers the Listings bar chart",
    dependencies=[Depends(admin_or_super)],
)
def listings_by_type(db: Session = Depends(get_db)):
    rows = (
        db.query(Listing.type, func.count(Listing.id))
        .group_by(Listing.type)
        .all()
    )
    counts = {t.value: 0 for t in ListingType}
    for t, c in rows:
        counts[t.value if hasattr(t, "value") else t] = c
    return [{"type": k, "count": v} for k, v in counts.items()]


@router.get(
    "/dashboard/revenue-trend",
    summary="Paid revenue and booking count per day for the last N days — powers the Revenue chart",
    dependencies=[Depends(admin_or_super)],
)
def revenue_trend(days: int = Query(14, ge=1, le=90), db: Session = Depends(get_db)):
    from datetime import datetime, timedelta

    start = datetime.utcnow() - timedelta(days=days - 1)
    start = start.replace(hour=0, minute=0, second=0, microsecond=0)

    bookings = (
        db.query(Booking)
        .filter(Booking.created_at >= start)
        .all()
    )

    by_day = {}
    for i in range(days):
        day = (start + timedelta(days=i)).date().isoformat()
        by_day[day] = {"date": day, "revenue": 0.0, "bookings": 0}

    for b in bookings:
        day = b.created_at.date().isoformat()
        if day in by_day:
            by_day[day]["bookings"] += 1
            if b.payment_status == PaymentStatus.PAID:
                by_day[day]["revenue"] += b.total_amount

    return list(by_day.values())


# ---------- Users ----------

@router.get(
    "/users",
    response_model=List[AdminUserOut],
    summary="List all platform users",
    dependencies=[Depends(admin_or_super)],
)
def list_users(
    role: Optional[UserRole] = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(User)
    if role:
        query = query.filter(User.role == role)
    return query.order_by(User.created_at.desc()).all()


@router.put(
    "/users/{user_id}/status",
    response_model=AdminUserOut,
    summary="Verify or (de)activate a user — e.g. approve an Agent/Distributor",
    dependencies=[Depends(admin_or_super)],
)
def update_user_status(user_id: int, payload: UpdateUserStatus, db: Session = Depends(get_db),
                       me: User = Depends(get_current_user)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.role in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
        raise HTTPException(status_code=403, detail="Use the Admins endpoints to manage admin accounts.")

    changes = []
    if payload.is_verified is not None and payload.is_verified != user.is_verified:
        user.is_verified = payload.is_verified
        changes.append("verified" if payload.is_verified else "unverified")
    if payload.is_active is not None and payload.is_active != user.is_active:
        user.is_active = payload.is_active
        changes.append("reactivated" if payload.is_active else "suspended")

    db.commit()
    if changes:
        audit(db, me, f"user.{changes[0]}", f"{user.role.value.title()} #{user.id} {user.full_name}", ", ".join(changes))
    db.refresh(user)
    return user


# ---------- Listings (moderation) ----------

@router.get(
    "/listings",
    response_model=List[ListingOut],
    summary="List every listing on the platform, including inactive ones",
    dependencies=[Depends(admin_or_super)],
)
def list_all_listings(
    type: Optional[str] = Query(None, description="Filter by listing type, e.g. hotel, flight, cruise, visa"),
    db: Session = Depends(get_db),
):
    query = db.query(Listing)
    if type:
        query = query.filter(Listing.type == type)
    return query.order_by(Listing.created_at.desc()).all()


@router.put(
    "/listings/{listing_id}",
    response_model=ListingOut,
    summary="Edit any listing's details (full CRUD — Admin/Super Admin can edit listings from any owner)",
    dependencies=[Depends(admin_or_super)],
)
def admin_update_listing(listing_id: int, payload: ListingCreate, db: Session = Depends(get_db)):
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found.")

    for field, value in payload.model_dump().items():
        setattr(listing, field, value)
    db.commit()
    db.refresh(listing)
    return listing


@router.delete(
    "/listings/{listing_id}",
    status_code=204,
    summary="Permanently delete a listing (full CRUD — different from take-down, which just hides it)",
    dependencies=[Depends(admin_or_super)],
)
def admin_delete_listing(listing_id: int, db: Session = Depends(get_db)):
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found.")
    db.delete(listing)
    db.commit()
    return None


@router.put(
    "/listings/{listing_id}/toggle-active",
    response_model=ListingOut,
    summary="Approve (activate) or take down (deactivate) a listing",
    dependencies=[Depends(admin_or_super)],
)
def toggle_listing_active(listing_id: int, db: Session = Depends(get_db)):
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found.")
    listing.is_active = not listing.is_active
    db.commit()
    db.refresh(listing)
    return listing


# ---------- Bookings (overview) ----------

@router.get(
    "/bookings",
    response_model=List[BookingOut],
    summary="List every booking on the platform",
    dependencies=[Depends(admin_or_super)],
)
def list_all_bookings(
    status_filter: Optional[BookingStatus] = Query(None, alias="status"),
    db: Session = Depends(get_db),
):
    query = db.query(Booking)
    if status_filter:
        query = query.filter(Booking.status == status_filter)
    return query.order_by(Booking.created_at.desc()).all()


# ---------- Payments ----------

@router.get(
    "/payments",
    response_model=List[PaymentTransactionOut],
    summary="List every payment transaction on the platform",
    dependencies=[Depends(admin_or_super)],
)
def list_payments(
    status_filter: Optional[PaymentStatus] = Query(None, alias="status"),
    db: Session = Depends(get_db),
):
    query = db.query(Booking).filter(Booking.payment_status != PaymentStatus.UNPAID)
    if status_filter:
        query = query.filter(Booking.payment_status == status_filter)

    bookings = query.order_by(Booking.created_at.desc()).all()
    out = []
    for b in bookings:
        out.append(PaymentTransactionOut(
            booking_id=b.id,
            customer_name=b.customer.full_name if b.customer else "—",
            customer_email=b.customer.email if b.customer else "—",
            listing_title=b.listing.title if b.listing else "—",
            amount=b.total_amount,
            payment_status=b.payment_status,
            payment_reference=b.payment_reference,
            card_last4=b.payment_card_last4,
            paid_at=b.paid_at,
            created_at=b.created_at,
        ))
    return out


# ---------- Reviews (moderation) ----------

@router.get(
    "/reviews",
    response_model=List[ReviewOut],
    summary="List every review on the platform",
    dependencies=[Depends(admin_or_super)],
)
def list_all_reviews(db: Session = Depends(get_db)):
    reviews = db.query(Review).order_by(Review.created_at.desc()).all()
    out = []
    for r in reviews:
        item = ReviewOut.model_validate(r)
        item.customer_name = r.customer.full_name if r.customer else None
        out.append(item)
    return out


@router.delete(
    "/reviews/{review_id}",
    status_code=204,
    summary="Remove an inappropriate review",
    dependencies=[Depends(admin_or_super)],
)
def delete_review(review_id: int, db: Session = Depends(get_db)):
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found.")
    listing_id = review.listing_id
    db.delete(review)
    db.commit()

    # Recompute the listing's average rating after removal
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
    return None


# ---------- Admin account management (Super Admin only) ----------

@router.get(
    "/admins",
    response_model=List[AdminUserOut],
    summary="List all Admin / Super Admin accounts (Super Admin only)",
    dependencies=[Depends(super_admin_only)],
)
def list_admins(db: Session = Depends(get_db)):
    return (
        db.query(User)
        .filter(User.role.in_([UserRole.ADMIN, UserRole.SUPER_ADMIN]))
        .order_by(User.created_at.desc())
        .all()
    )


@router.post(
    "/admins",
    response_model=TokenResponse,
    status_code=201,
    summary="Create a new Admin account (Super Admin only)",
    dependencies=[Depends(super_admin_only)],
)
def create_admin(payload: CreateAdminRequest, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="An account with this email already exists.")

    user = User(
        full_name=payload.full_name,
        email=payload.email,
        phone=payload.phone,
        password_hash=hash_password(payload.password),
        role=UserRole.ADMIN,
        is_verified=True,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    audit(db, me, "employee.created", f"Admin #{user.id} {user.full_name}", user.email)

    token = create_access_token({"sub": str(user.id), "role": user.role.value})
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.delete(
    "/admins/{admin_id}",
    status_code=204,
    summary="Revoke an Admin account (Super Admin only)",
    dependencies=[Depends(super_admin_only)],
)
def revoke_admin(admin_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if admin_id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot revoke your own account.")

    admin = db.query(User).filter(User.id == admin_id, User.role == UserRole.ADMIN).first()
    if not admin:
        raise HTTPException(status_code=404, detail="Admin account not found.")

    admin.is_active = False
    db.commit()
    audit(db, current_user, "employee.revoked", f"Admin #{admin.id} {admin.full_name}", admin.email)
    return None
