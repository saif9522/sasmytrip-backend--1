import secrets
from typing import List
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Booking, Listing, User, UserRole, BookingStatus, PaymentStatus, Notification
from app.schemas.schemas import BookingCreate, BookingOut, TravellerDetailsUpdate, PaymentRequest
from app.core.security import get_current_user, require_roles

router = APIRouter(prefix="/api/bookings", tags=["Bookings"])


@router.post(
    "",
    response_model=BookingOut,
    status_code=201,
    summary="Step 1 — Create a booking (Customer only)",
    description="Creates the booking in `pending` / `unpaid` state. Continue the flow with "
                "`PUT /bookings/{id}/traveller-details` and `POST /bookings/{id}/pay`.",
    dependencies=[Depends(require_roles(UserRole.CUSTOMER))],
)
def create_booking(
    payload: BookingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    listing = db.query(Listing).filter(Listing.id == payload.listing_id, Listing.is_active == True).first()  # noqa: E712
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found or no longer available.")

    booking = Booking(
        customer_id=current_user.id,
        listing_id=listing.id,
        travellers=payload.travellers,
        travel_date=payload.travel_date,
        total_amount=listing.price * max(payload.travellers, 1),
        status=BookingStatus.PENDING,
        payment_status=PaymentStatus.UNPAID,
        # Pre-fill traveller contact from the account — the customer can edit it in step 2.
        traveller_name=current_user.full_name,
        traveller_email=current_user.email,
        traveller_phone=current_user.phone,
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)
    return booking


# IMPORTANT — route ordering: every literal single-segment path (/my,
# /received) MUST be declared BEFORE the bare `/{booking_id}` route below.
# FastAPI/Starlette matches routes in declaration order, and `/{booking_id}`
# matches ANY single path segment — including the literal words "my" or
# "received" — so if it were declared first, those routes would become
# unreachable and instead fail with a confusing 422 "unable to parse string
# as an integer" error. (This exact bug shipped once already — don't reorder
# these without keeping /my and /received above /{booking_id}.)

@router.get(
    "/my",
    response_model=List[BookingOut],
    summary="My bookings (Customer only)",
    dependencies=[Depends(require_roles(UserRole.CUSTOMER))],
)
def my_bookings(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return (
        db.query(Booking)
        .filter(Booking.customer_id == current_user.id)
        .order_by(Booking.created_at.desc())
        .all()
    )


@router.get(
    "/received",
    response_model=List[BookingOut],
    summary="Bookings made on my listings (Agent / Distributor only)",
    dependencies=[Depends(require_roles(UserRole.AGENT, UserRole.DISTRIBUTOR))],
)
def received_bookings(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return (
        db.query(Booking)
        .join(Listing, Booking.listing_id == Listing.id)
        .filter(Listing.owner_id == current_user.id)
        .order_by(Booking.created_at.desc())
        .all()
    )


@router.get(
    "/{booking_id}",
    response_model=BookingOut,
    summary="Get a single booking (for the booking-flow / confirmation pages)",
)
def get_booking(booking_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found.")
    if booking.customer_id != current_user.id and current_user.role not in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
        raise HTTPException(status_code=403, detail="You can only view your own bookings.")
    return booking


@router.put(
    "/{booking_id}/traveller-details",
    response_model=BookingOut,
    summary="Step 2 — Save traveller details (Customer only)",
    dependencies=[Depends(require_roles(UserRole.CUSTOMER))],
)
def update_traveller_details(
    booking_id: int,
    payload: TravellerDetailsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booking = db.query(Booking).filter(Booking.id == booking_id, Booking.customer_id == current_user.id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found.")
    if booking.status != BookingStatus.PENDING:
        raise HTTPException(status_code=400, detail="Traveller details can only be edited before payment.")

    booking.traveller_name = payload.traveller_name
    booking.traveller_email = payload.traveller_email
    booking.traveller_phone = payload.traveller_phone
    db.commit()
    db.refresh(booking)
    return booking


@router.post(
    "/{booking_id}/pay",
    response_model=BookingOut,
    summary="Step 3 — Pay for a booking (Customer only)",
    description=(
        "**Demo/test payment.** No real gateway is charged and raw card numbers "
        "are never stored — only the last 4 digits are kept, same as a real "
        "provider would return. Use test card `4242 4242 4242 4242` for a "
        "successful charge, or `4000 0000 0000 0002` to simulate a decline.\n\n"
        "Before going live, replace this with a real Razorpay/Stripe integration "
        "that verifies a signed payment confirmation rather than trusting the client."
    ),
    dependencies=[Depends(require_roles(UserRole.CUSTOMER))],
)
def pay_for_booking(
    booking_id: int,
    payload: PaymentRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booking = db.query(Booking).filter(Booking.id == booking_id, Booking.customer_id == current_user.id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found.")
    if booking.payment_status == PaymentStatus.PAID:
        raise HTTPException(status_code=400, detail="This booking has already been paid for.")
    if not booking.traveller_name or not booking.traveller_email:
        raise HTTPException(status_code=400, detail="Add traveller details before paying.")

    card_number = payload.card_number.replace(" ", "")
    if len(card_number) < 12 or not card_number.isdigit():
        raise HTTPException(status_code=400, detail="Enter a valid card number.")

    last4 = card_number[-4:]
    booking.payment_card_last4 = last4

    # Simulated gateway response — mirrors how Stripe/Razorpay test-mode
    # decline cards work, so the flow can be demoed without a real key.
    if card_number == "4000000000000002":
        booking.payment_status = PaymentStatus.FAILED
        booking.payment_failure_reason = "Card declined by issuing bank (test decline card)."
        db.commit()
        raise HTTPException(
            status_code=402,
            detail="Your card was declined. Try test card 4242 4242 4242 4242 instead.",
        )

    booking.payment_status = PaymentStatus.PAID
    booking.status = BookingStatus.CONFIRMED
    booking.payment_reference = f"PAY-{secrets.token_hex(6).upper()}"
    booking.payment_failure_reason = None
    booking.paid_at = datetime.utcnow()
    db.add(Notification(
        user_id=current_user.id,
        title="Booking confirmed",
        message=f"Your booking #{booking.id} is confirmed. Reference: {booking.payment_reference}",
    ))
    db.commit()
    db.refresh(booking)
    return booking


@router.put(
    "/{booking_id}/cancel",
    response_model=BookingOut,
    summary="Cancel a booking (Customer only)",
    dependencies=[Depends(require_roles(UserRole.CUSTOMER))],
)
def cancel_booking(booking_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    booking = db.query(Booking).filter(Booking.id == booking_id, Booking.customer_id == current_user.id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found.")
    if booking.status == BookingStatus.CANCELLED:
        raise HTTPException(status_code=400, detail="This booking is already cancelled.")

    booking.status = BookingStatus.CANCELLED
    if booking.payment_status == PaymentStatus.PAID:
        booking.payment_status = PaymentStatus.REFUNDED
    db.commit()
    db.refresh(booking)
    return booking
