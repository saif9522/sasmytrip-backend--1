from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field

from app.models.models import UserRole, ListingType, BookingStatus, PaymentStatus


# ---------- Auth ----------

class RegisterRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=120, examples=["Ananya Rao"])
    email: EmailStr = Field(..., examples=["ananya@example.com"])
    phone: Optional[str] = Field(None, examples=["+91 98765 43210"])
    password: str = Field(..., min_length=6, examples=["StrongPass123"])
    role: UserRole = Field(..., examples=["customer"])
    company_name: Optional[str] = Field(None, examples=["Skyline Travels Pvt Ltd"])
    gstin: Optional[str] = Field(None, examples=["22AAAAA0000A1Z5"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    role: UserRole = Field(..., description="The portal the user is logging into")


class UserOut(BaseModel):
    id: int
    full_name: str
    email: EmailStr
    phone: Optional[str] = None
    role: UserRole
    company_name: Optional[str] = None
    is_verified: bool
    created_at: datetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    message: str
    # NOTE: In production this token is emailed, never returned in the API response.
    # It's returned here only because this starter has no email service wired up yet —
    # see app/routers/auth.py for the TODO on wiring a real email provider.
    dev_reset_token: Optional[str] = None


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=6)


class SendOtpRequest(BaseModel):
    phone: str = Field(..., min_length=6, max_length=20, examples=["+91 98765 43210"])
    role: UserRole = Field(..., description="Must match the role the phone number was registered under")


class SendOtpResponse(BaseModel):
    message: str
    # NOTE: returned only because this starter has no SMS provider wired up yet.
    # In production this goes out via SMS (Twilio/MSG91/etc.) and is never in the API response.
    dev_otp: Optional[str] = None


class VerifyOtpRequest(BaseModel):
    phone: str = Field(..., min_length=6, max_length=20)
    otp: str = Field(..., min_length=4, max_length=6)
    role: UserRole


# ---------- Listings ----------

class ListingCreate(BaseModel):
    type: ListingType
    title: str
    location: Optional[str] = None
    description: Optional[str] = None
    price: float
    image_url: Optional[str] = None


class ListingOut(BaseModel):
    id: int
    type: ListingType
    title: str
    location: Optional[str] = None
    description: Optional[str] = None
    price: float
    rating: float
    review_count: int
    image_url: Optional[str] = None
    is_active: bool
    owner_id: int
    created_at: datetime

    class Config:
        from_attributes = True


# ---------- Bookings ----------

class BookingCreate(BaseModel):
    listing_id: int
    travellers: int = 1
    travel_date: Optional[datetime] = None


class TravellerDetailsUpdate(BaseModel):
    traveller_name: str = Field(..., min_length=2, max_length=120)
    traveller_email: EmailStr
    traveller_phone: str = Field(..., min_length=6, max_length=20)


class PaymentRequest(BaseModel):
    """
    Demo/test payment — no real card is charged and raw card numbers are
    never stored (only the last 4 digits, same as a real gateway would return).

    Use these test card numbers to see both outcomes:
      4242 4242 4242 4242  -> succeeds
      4000 0000 0000 0002  -> declines (simulates a failed charge)
      any other 16-digit number -> succeeds
    """
    card_number: str = Field(..., examples=["4242424242424242"], description="Digits only, spaces are stripped")
    card_expiry: str = Field(..., examples=["12/28"], description="MM/YY")
    card_cvv: str = Field(..., examples=["123"], min_length=3, max_length=4)
    card_holder: Optional[str] = Field(None, examples=["Ananya Rao"])


class BookingOut(BaseModel):
    id: int
    customer_id: int
    listing_id: int
    travellers: int
    travel_date: Optional[datetime] = None
    status: BookingStatus
    total_amount: float
    created_at: datetime

    traveller_name: Optional[str] = None
    traveller_email: Optional[str] = None
    traveller_phone: Optional[str] = None

    payment_status: PaymentStatus
    payment_reference: Optional[str] = None
    payment_card_last4: Optional[str] = None
    paid_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PaymentTransactionOut(BaseModel):
    booking_id: int
    customer_name: str
    customer_email: str
    listing_title: str
    amount: float
    payment_status: PaymentStatus
    payment_reference: Optional[str] = None
    card_last4: Optional[str] = None
    paid_at: Optional[datetime] = None
    created_at: datetime


# ---------- Wishlist ----------

class WishlistOut(BaseModel):
    id: int
    listing: ListingOut
    created_at: datetime

    class Config:
        from_attributes = True


# ---------- Reviews ----------

class ReviewCreate(BaseModel):
    listing_id: int
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = Field(None, max_length=1000)


class ReviewOut(BaseModel):
    id: int
    customer_id: int
    listing_id: int
    rating: int
    comment: Optional[str] = None
    created_at: datetime
    customer_name: Optional[str] = None

    class Config:
        from_attributes = True


# ---------- Notifications ----------

class NotificationOut(BaseModel):
    id: int
    title: str
    message: Optional[str] = None
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ---------- Admin ----------

class DashboardStats(BaseModel):
    total_users: int
    total_customers: int
    total_agents: int
    total_distributors: int
    pending_verifications: int
    total_listings: int
    active_listings: int
    total_bookings: int
    pending_bookings: int
    confirmed_bookings: int
    cancelled_bookings: int
    completed_bookings: int
    total_revenue: float
    paid_revenue: float
    failed_payments: int


class AdminUserOut(UserOut):
    is_active: bool


class UpdateUserStatus(BaseModel):
    is_active: Optional[bool] = None
    is_verified: Optional[bool] = None


class CreateAdminRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=120)
    email: EmailStr
    phone: Optional[str] = None
    password: str = Field(..., min_length=6)
    role: UserRole = Field(UserRole.ADMIN, description="Must be 'admin' — only a Super Admin can promote to 'super_admin' directly in the database.")
