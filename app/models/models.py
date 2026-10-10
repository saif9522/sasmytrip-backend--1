import enum
from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Enum, Text, UniqueConstraint
)
from sqlalchemy.orm import relationship

from app.database import Base


class UserRole(str, enum.Enum):
    CUSTOMER = "customer"        # regular traveller / end user
    AGENT = "agent"               # travel agent — manages bookings on behalf of customers
    DISTRIBUTOR = "distributor"   # wholesale distributor — supplies hotel/flight/package inventory
    ADMIN = "admin"               # platform staff — verifies partners, moderates listings/bookings
    SUPER_ADMIN = "super_admin"   # full control — everything Admin can do, plus manages Admin accounts


class BookingStatus(str, enum.Enum):
    PENDING = "pending"       # created, traveller details + payment not yet done
    CONFIRMED = "confirmed"   # payment successful
    CANCELLED = "cancelled"
    COMPLETED = "completed"   # trip has taken place


class PaymentStatus(str, enum.Enum):
    UNPAID = "unpaid"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(120), nullable=False)
    email = Column(String(160), unique=True, index=True, nullable=False)
    phone = Column(String(20), nullable=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), nullable=False, default=UserRole.CUSTOMER, index=True)

    # Only relevant for AGENT / DISTRIBUTOR roles
    company_name = Column(String(160), nullable=True)
    gstin = Column(String(20), nullable=True)
    is_verified = Column(Boolean, default=False)  # agents/distributors need admin verification

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Agents only: commission % on their bookings (None = use the platform default from Settings)
    agent_commission_percent = Column(Float, nullable=True)

    # Password reset
    reset_token = Column(String(255), nullable=True)
    reset_token_expires = Column(DateTime, nullable=True)

    listings = relationship("Listing", back_populates="owner")
    bookings = relationship("Booking", back_populates="customer")
    wishlist_items = relationship("WishlistItem", back_populates="customer")
    reviews = relationship("Review", back_populates="customer")


class ListingType(str, enum.Enum):
    HOTEL = "hotel"
    FLIGHT = "flight"
    PACKAGE = "package"
    TRAIN = "train"
    BUS = "bus"
    CAB = "cab"
    ACTIVITY = "activity"
    CRUISE = "cruise"
    HAJJ_UMRAH = "hajj_umrah"
    TRAVEL_INSURANCE = "travel_insurance"
    MONEY_EXCHANGE = "money_exchange"
    VISA = "visa"


class Listing(Base):
    """A sellable inventory item — hotel room, flight route, or holiday package.
    Created by an AGENT or DISTRIBUTOR account."""
    __tablename__ = "listings"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(Enum(ListingType), nullable=False, index=True)
    title = Column(String(160), nullable=False)
    location = Column(String(160), nullable=True)
    description = Column(Text, nullable=True)
    price = Column(Float, nullable=False)
    rating = Column(Float, default=0.0)
    review_count = Column(Integer, default=0)
    image_url = Column(String(500), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    owner = relationship("User", back_populates="listings")

    bookings = relationship("Booking", back_populates="listing")
    wishlisted_by = relationship("WishlistItem", back_populates="listing")
    reviews = relationship("Review", back_populates="listing")


class Booking(Base):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    listing_id = Column(Integer, ForeignKey("listings.id"), nullable=False)
    travellers = Column(Integer, default=1)
    travel_date = Column(DateTime, nullable=True)
    status = Column(Enum(BookingStatus), default=BookingStatus.PENDING, index=True)
    total_amount = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Traveller details — filled during the booking flow, before payment
    traveller_name = Column(String(120), nullable=True)
    traveller_email = Column(String(160), nullable=True)
    traveller_phone = Column(String(20), nullable=True)

    # Payment
    payment_status = Column(Enum(PaymentStatus), default=PaymentStatus.UNPAID, index=True)
    payment_reference = Column(String(64), nullable=True)
    payment_card_last4 = Column(String(4), nullable=True)
    payment_failure_reason = Column(String(255), nullable=True)
    paid_at = Column(DateTime, nullable=True)

    customer = relationship("User", back_populates="bookings")
    listing = relationship("Listing", back_populates="bookings")


class WishlistItem(Base):
    __tablename__ = "wishlist_items"
    __table_args__ = (UniqueConstraint("customer_id", "listing_id", name="uq_wishlist_customer_listing"),)

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    listing_id = Column(Integer, ForeignKey("listings.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    customer = relationship("User", back_populates="wishlist_items")
    listing = relationship("Listing", back_populates="wishlisted_by")


class Review(Base):
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    listing_id = Column(Integer, ForeignKey("listings.id"), nullable=False)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=True)
    rating = Column(Integer, nullable=False)  # 1–5
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    customer = relationship("User", back_populates="reviews")
    listing = relationship("Listing", back_populates="reviews")


class Notification(Base):
    """In-app notifications for a user — booking confirmations, verification updates, etc."""
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(160), nullable=False)
    message = Column(Text, nullable=True)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class OtpCode(Base):
    """One-time codes for mobile OTP login. Stored in the same SQLite database
    as everything else — no separate service needed for this starter."""
    __tablename__ = "otp_codes"

    id = Column(Integer, primary_key=True, index=True)
    phone = Column(String(20), nullable=False, index=True)
    role = Column(Enum(UserRole), nullable=False)
    code = Column(String(6), nullable=False)
    is_used = Column(Boolean, default=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class SupplierBookingStatus(str, enum.Enum):
    PENDING = "pending"                       # created, awaiting payment
    CONFIRMED = "confirmed"                   # paid + ticketed / vouchered at TBO
    FAILED = "failed"                         # paid but supplier booking failed (payment refunded)
    CANCELLATION_REQUESTED = "cancellation_requested"
    CANCELLED = "cancelled"


class SupplierBooking(Base):
    """A live flight/hotel booking made through the TBO API (not a partner listing)."""
    __tablename__ = "supplier_bookings"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    supplier = Column(String(20), default="tbo")
    product = Column(String(20), nullable=False, index=True)      # "flight" | "hotel"
    status = Column(Enum(SupplierBookingStatus), default=SupplierBookingStatus.PENDING, index=True)

    title = Column(String(255), nullable=False)                    # e.g. "DEL → BOM" / hotel name
    subtitle = Column(String(255), nullable=True)                  # e.g. "IndiGo 6E-203 · 2 travellers"
    travel_date = Column(String(20), nullable=True)                # ISO date
    end_date = Column(String(20), nullable=True)

    currency = Column(String(5), default="INR")
    amount = Column(Float, nullable=False)                         # what the customer pays (incl. markup)
    supplier_amount = Column(Float, nullable=True)                 # TBO price

    # Contact
    contact_name = Column(String(160), nullable=True)
    contact_email = Column(String(160), nullable=True)
    contact_phone = Column(String(30), nullable=True)

    # JSON blobs (stored as text for SQLite)
    request_json = Column(Text, nullable=True)                     # what we need to book: trace id, indexes, pax ...
    summary_json = Column(Text, nullable=True)                     # itinerary / room snapshot shown to the customer
    supplier_json = Column(Text, nullable=True)                    # TBO results: PNRs, booking ids, tickets ...

    # Supplier references
    pnr = Column(String(120), nullable=True)
    supplier_booking_id = Column(String(120), nullable=True)
    confirmation_no = Column(String(120), nullable=True)
    change_request_id = Column(String(120), nullable=True)
    error_message = Column(Text, nullable=True)

    # Payment (demo — replace with Razorpay/Stripe before going live)
    payment_status = Column(Enum(PaymentStatus), default=PaymentStatus.UNPAID)
    payment_reference = Column(String(64), nullable=True)
    payment_card_last4 = Column(String(4), nullable=True)
    paid_at = Column(DateTime, nullable=True)

    # Set when a Travel Agent made the booking
    agent_commission = Column(Float, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    customer = relationship("User")


class Offer(Base):
    """Promotional offer shown on the home page Offers section. Managed by Admin."""
    __tablename__ = "offers"

    id = Column(Integer, primary_key=True, index=True)
    category = Column(String(30), nullable=False, index=True)   # flights / hotels / holidays / bank / trains / cabs / bus / forex / visa
    tag = Column(String(40), nullable=True)                      # small label, e.g. "INTL FLIGHTS"
    title = Column(String(160), nullable=False)
    description = Column(String(300), nullable=True)
    image_url = Column(String(500), nullable=True)
    badge = Column(String(60), nullable=True)                    # e.g. bank / partner name shown on the image
    promo_code = Column(String(30), nullable=True)
    cta_label = Column(String(30), default="Book now")
    cta_link = Column(String(300), default="/flights")
    terms = Column(Text, nullable=True)
    valid_till = Column(String(20), nullable=True)               # ISO date; hidden from the site after this day
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class HomeCard(Base):
    """Image cards for home-page carousels (airlines, hotel collections, curated lists, hidden gems)."""
    __tablename__ = "home_cards"

    id = Column(Integer, primary_key=True, index=True)
    section = Column(String(30), nullable=False, index=True)
    title = Column(String(160), nullable=False)
    subtitle = Column(String(200), nullable=True)
    badge = Column(String(30), nullable=True)       # e.g. "TOP 8"
    image_url = Column(String(500), nullable=True)
    link = Column(String(300), nullable=True)
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class LoginSession(Base):
    """One row per login — used for working hours, 'online now' and login history."""
    __tablename__ = "login_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    role = Column(String(20), nullable=False, index=True)
    method = Column(String(20), default="password")       # password | otp | register
    ip = Column(String(64), nullable=True)
    user_agent = Column(String(300), nullable=True)
    login_at = Column(DateTime, default=datetime.utcnow, index=True)
    last_seen_at = Column(DateTime, default=datetime.utcnow)
    logout_at = Column(DateTime, nullable=True)


class AuditLog(Base):
    """Who did what — admin/employee actions and agent bookings."""
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    user_name = Column(String(120), nullable=True)
    role = Column(String(20), nullable=True, index=True)
    action = Column(String(60), nullable=False, index=True)   # e.g. agent.approved, offer.updated, booking.confirmed
    target = Column(String(160), nullable=True)               # e.g. "User #12", "Booking #40"
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class AppSetting(Base):
    """Platform settings editable from Admin → Settings (key/value)."""
    __tablename__ = "app_settings"

    key = Column(String(60), primary_key=True)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
