"""Request/response schemas for the TBO-powered flight & hotel endpoints."""
import json
import re
from datetime import date, datetime
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.models.models import PaymentStatus, SupplierBookingStatus

NAME_RE = re.compile(r"^[A-Za-z ]+$")


# ------------------------------------------------------------------ flights

class FlightSearchRequest(BaseModel):
    origin: str = Field(..., min_length=3, max_length=3, examples=["DEL"])
    destination: str = Field(..., min_length=3, max_length=3, examples=["BOM"])
    depart_date: date = Field(..., examples=["2026-11-20"])
    return_date: Optional[date] = None
    adults: int = Field(1, ge=1, le=9)
    children: int = Field(0, ge=0, le=8)
    infants: int = Field(0, ge=0, le=4)
    cabin: Literal["all", "economy", "premium_economy", "business", "premium_business", "first"] = "economy"
    direct_only: bool = False

    @model_validator(mode="after")
    def check(self):
        if self.origin.upper() == self.destination.upper():
            raise ValueError("Origin and destination must be different.")
        if self.depart_date < date.today():
            raise ValueError("Departure date can't be in the past.")
        if self.return_date and self.return_date < self.depart_date:
            raise ValueError("Return date must be on or after the departure date.")
        if self.adults + self.children > 9:
            raise ValueError("A maximum of 9 adults + children can be booked together.")
        if self.infants > self.adults:
            raise ValueError("Each infant must travel with an adult.")
        return self


class TraceRequest(BaseModel):
    trace_id: str
    result_index: str


class Passenger(BaseModel):
    title: Literal["Mr", "Mrs", "Ms", "Miss", "Mstr"]
    first_name: str = Field(..., min_length=1, max_length=32)
    last_name: str = Field(..., min_length=2, max_length=32)
    pax_type: Literal[1, 2, 3] = 1          # 1 adult, 2 child, 3 infant (TBO PaxType)
    gender: Literal["male", "female"] = "male"
    date_of_birth: Optional[date] = None
    nationality: str = "IN"
    passport_no: Optional[str] = None
    passport_expiry: Optional[date] = None
    passport_issue_date: Optional[date] = None
    pan: Optional[str] = None

    @field_validator("first_name", "last_name")
    @classmethod
    def letters_only(cls, v: str) -> str:
        v = " ".join(v.split())
        if not NAME_RE.match(v):
            raise ValueError("Names may only contain letters and spaces (as on the ID).")
        return v

    @model_validator(mode="after")
    def dob_for_minors(self):
        if self.pax_type in (2, 3) and not self.date_of_birth:
            raise ValueError("Date of birth is required for children and infants.")
        return self


class Contact(BaseModel):
    name: Optional[str] = None
    email: EmailStr
    phone: str = Field(..., min_length=7, max_length=15)
    country_code: str = "+91"
    address: Optional[str] = None
    city: Optional[str] = None


class GSTDetails(BaseModel):
    company_name: str
    gst_number: str
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    address: Optional[str] = None


class FlightBookingCreate(BaseModel):
    trace_id: str
    result_indexes: List[str] = Field(..., min_length=1, max_length=2,
                                      description="One index, or two for a domestic return (outbound + inbound).")
    passengers: List[Passenger] = Field(..., min_length=1, max_length=13)
    contact: Contact
    gst: Optional[GSTDetails] = None


# ------------------------------------------------------------------ hotels

class RoomOccupancy(BaseModel):
    adults: int = Field(2, ge=1, le=8)
    children: int = Field(0, ge=0, le=4)
    children_ages: List[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def ages(self):
        if len(self.children_ages) != self.children:
            raise ValueError("Give an age for every child.")
        if any(a < 0 or a > 17 for a in self.children_ages):
            raise ValueError("Child ages must be between 0 and 17.")
        return self


class HotelSearchRequest(BaseModel):
    city_code: str = Field(..., examples=["130443"])
    check_in: date
    check_out: date
    rooms: List[RoomOccupancy] = Field(default_factory=lambda: [RoomOccupancy()], min_length=1, max_length=6)
    nationality: str = "IN"
    refundable_only: bool = False
    meal_type: Literal["All", "WithMeal", "RoomOnly"] = "All"
    star_rating: Optional[int] = Field(None, ge=1, le=5)

    @model_validator(mode="after")
    def dates(self):
        if self.check_in < date.today():
            raise ValueError("Check-in can't be in the past.")
        if self.check_out <= self.check_in:
            raise ValueError("Check-out must be after check-in.")
        if (self.check_out - self.check_in).days > 30:
            raise ValueError("Stays longer than 30 nights can't be booked online.")
        return self


class HotelRoomsRequest(BaseModel):
    hotel_code: str
    check_in: date
    check_out: date
    rooms: List[RoomOccupancy] = Field(default_factory=lambda: [RoomOccupancy()], min_length=1, max_length=6)
    nationality: str = "IN"


class PreBookRequest(BaseModel):
    booking_code: str


class HotelGuest(BaseModel):
    title: Literal["Mr", "Mrs", "Ms", "Miss", "Mstr"]
    first_name: str = Field(..., min_length=1, max_length=50)
    last_name: str = Field(..., min_length=2, max_length=50)
    pax_type: Literal[1, 2] = 1
    age: Optional[int] = Field(None, ge=0, le=120)
    pan: Optional[str] = None
    passport_no: Optional[str] = None

    @field_validator("first_name", "last_name")
    @classmethod
    def letters_only(cls, v: str) -> str:
        v = " ".join(v.split())
        if not NAME_RE.match(v):
            raise ValueError("Names may only contain letters and spaces.")
        return v


class HotelBookingCreate(BaseModel):
    booking_code: str
    hotel_code: str
    hotel_name: Optional[str] = None
    check_in: date
    check_out: date
    nationality: str = "IN"
    rooms: List[RoomOccupancy] = Field(..., min_length=1, max_length=6)
    guests: List[List[HotelGuest]] = Field(..., description="One list of guests per room; first guest of each room is the lead.")
    contact: Contact

    @model_validator(mode="after")
    def guests_match_rooms(self):
        if len(self.guests) != len(self.rooms):
            raise ValueError("Add guest details for every room.")
        for i, (room, guests) in enumerate(zip(self.rooms, self.guests), start=1):
            if len(guests) != room.adults + room.children:
                raise ValueError(f"Room {i}: enter details for all {room.adults + room.children} guests.")
        return self


# ------------------------------------------------------------------ bookings

class TravelPaymentRequest(BaseModel):
    card_number: str
    card_expiry: str
    card_cvv: str
    card_holder: str


class CancelRequest(BaseModel):
    remarks: Optional[str] = "Cancelled by customer"


class SupplierBookingOut(BaseModel):
    id: int
    product: str
    status: SupplierBookingStatus
    title: str
    subtitle: Optional[str] = None
    travel_date: Optional[str] = None
    end_date: Optional[str] = None
    currency: str
    amount: float
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    pnr: Optional[str] = None
    supplier_booking_id: Optional[str] = None
    confirmation_no: Optional[str] = None
    change_request_id: Optional[str] = None
    error_message: Optional[str] = None
    payment_status: PaymentStatus
    payment_reference: Optional[str] = None
    payment_card_last4: Optional[str] = None
    paid_at: Optional[datetime] = None
    created_at: datetime
    summary: Any = None
    supplier: Any = None

    @classmethod
    def from_model(cls, b) -> "SupplierBookingOut":
        data = {c: getattr(b, c) for c in cls.model_fields if hasattr(b, c) and c not in ("summary", "supplier")}
        data["status"] = b.status
        data["summary"] = json.loads(b.summary_json) if b.summary_json else None
        sup = json.loads(b.supplier_json) if b.supplier_json else None
        data["supplier"] = sup
        return cls(**data)


class AdminSupplierBookingOut(SupplierBookingOut):
    customer_id: int
    supplier_amount: Optional[float] = None

    @classmethod
    def from_model(cls, b):
        base = SupplierBookingOut.from_model(b).model_dump()
        return cls(**base, customer_id=b.customer_id, supplier_amount=b.supplier_amount)
