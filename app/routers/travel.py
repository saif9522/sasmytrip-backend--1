"""
Live flights & hotels powered by the TBO (tbo.com) API.

  /api/flights/*          search, fare rules, fare quote, SSR, create booking
  /api/hotels/*           city lookup, search, rooms, details, prebook, create booking
  /api/travel-bookings/*  my bookings, pay (-> ticket / voucher at TBO), cancel, refresh
  /api/tbo/status         admin: mode + agency balance
"""
import ipaddress
import json
import secrets
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.security import get_current_user, require_booker, require_roles
from app.database import get_db
from app.models.models import (
    Notification, PaymentStatus, SupplierBooking, SupplierBookingStatus, User, UserRole,
)
from app.schemas.travel import (
    AdminSupplierBookingOut, CancelRequest, FlightBookingCreate, FlightSearchRequest, HotelBookingCreate,
    HotelRoomsRequest, HotelSearchRequest, PreBookRequest, SupplierBookingOut, TraceRequest, TravelPaymentRequest,
)
from app.services.tbo import client as tbo_client
from app.services.tbo import config as tbo_config
from app.services.tbo import flights as tbo_flights
from app.services.tbo import hotels as tbo_hotels
from app.services.tbo.airports import city_of, search_airports
from app.services.tbo.config import apply_markup
from app.services.providers.base import ProviderError
from app.routers import services_api

flights_router = APIRouter(prefix="/api/flights", tags=["Flights (TBO live)"])
hotels_router = APIRouter(prefix="/api/hotels", tags=["Hotels (TBO live)"])
bookings_router = APIRouter(prefix="/api/travel-bookings", tags=["Flight & Hotel bookings (TBO)"])
admin_router = APIRouter(prefix="/api/tbo", tags=["TBO admin"])


# ------------------------------------------------------------------ helpers

def end_user_ip(request: Request) -> str:
    """TBO wants the traveller's public IP; fall back to the server IP for private/local addresses."""
    raw = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() or (request.client.host if request.client else "")
    try:
        ip = ipaddress.ip_address(raw)
        if ip.version == 4 and ip.is_global:
            return raw
    except ValueError:
        pass
    return tbo_config.settings.server_ip


def tbo_call_error(e: tbo_client.TBOError) -> HTTPException:
    return HTTPException(status_code=e.status_code, detail=e.message)


def _dump(obj) -> str:
    return json.dumps(obj, default=str)


def _load(text: Optional[str]):
    return json.loads(text) if text else {}


# ================================================================== FLIGHTS

@flights_router.get("/airports", summary="Airport autocomplete")
def airports(q: str = Query("", max_length=60)):
    return search_airports(q)


@flights_router.post("/search", summary="Search flights (TBO Search)")
async def flight_search(payload: FlightSearchRequest, request: Request):
    try:
        return await tbo_flights.search(
            origin=payload.origin, destination=payload.destination,
            depart_date=payload.depart_date.isoformat(),
            return_date=payload.return_date.isoformat() if payload.return_date else None,
            adults=payload.adults, children=payload.children, infants=payload.infants,
            cabin=payload.cabin, direct_only=payload.direct_only, end_user_ip=end_user_ip(request),
        )
    except tbo_client.TBOError as e:
        raise tbo_call_error(e)


@flights_router.post("/fare-rule", summary="Fare rules for a result (TBO FareRule)")
async def flight_fare_rule(payload: TraceRequest, request: Request):
    try:
        return await tbo_flights.fare_rule(payload.trace_id, payload.result_index, end_user_ip(request))
    except tbo_client.TBOError as e:
        raise tbo_call_error(e)


@flights_router.post("/fare-quote", summary="Re-price a result before booking (TBO FareQuote)")
async def flight_fare_quote(payload: TraceRequest, request: Request):
    try:
        return await tbo_flights.fare_quote(payload.trace_id, payload.result_index, end_user_ip(request))
    except tbo_client.TBOError as e:
        raise tbo_call_error(e)


@flights_router.post("/ssr", summary="Baggage / meal / seat options (TBO SSR)")
async def flight_ssr(payload: TraceRequest, request: Request):
    try:
        return await tbo_flights.ssr(payload.trace_id, payload.result_index, end_user_ip(request))
    except tbo_client.TBOError as e:
        raise tbo_call_error(e)


@flights_router.post(
    "/bookings", response_model=SupplierBookingOut, status_code=201,
    summary="Create a flight booking (Customer) — price is re-quoted server side",
    dependencies=[Depends(require_booker)],
)
async def create_flight_booking(payload: FlightBookingCreate, request: Request,
                                db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ip = end_user_ip(request)
    legs, quotes, supplier_total = [], [], 0.0
    pax = [p.model_dump() for p in payload.passengers]
    for k in ("date_of_birth", "passport_expiry", "passport_issue_date"):
        for p in pax:
            if p.get(k):
                p[k] = p[k].isoformat()

    try:
        for ri in payload.result_indexes:
            q = await tbo_flights.fare_quote_raw(payload.trace_id, ri, ip)
            raw = q["raw"]
            norm = tbo_flights.normalize_result(raw)
            _check_pax_counts(raw, pax)
            req = norm["requirements"]
            if req["passport_at_book"] and any(not p.get("passport_no") or not p.get("passport_expiry") for p in pax):
                raise HTTPException(status_code=422, detail="Passport number and expiry are required for every traveller on this flight.")
            if (req["pan_at_book"] or req["pan_at_ticket"]) and any(not p.get("pan") for p in pax if p["pax_type"] == 1):
                raise HTTPException(status_code=422, detail="PAN is required for adult travellers on this fare.")
            first, last = norm["legs"][0], norm["legs"][-1]
            tbo_pax = tbo_flights.build_passengers(
                pax, payload.contact.model_dump(), raw,
                first["origin"]["code"], last["destination"]["code"],
                payload.gst.model_dump() if payload.gst else None,
            )
            legs.append({"result_index": ri, "is_lcc": norm["is_lcc"], "passengers": tbo_pax})
            quotes.append({**norm, "is_price_changed": q["is_price_changed"]})
            supplier_total += norm["supplier_price"]
    except tbo_client.TBOError as e:
        raise tbo_call_error(e)

    first_leg = quotes[0]["legs"][0]
    origin, dest = first_leg["origin"], first_leg["destination"]
    seg0 = first_leg["segments"][0]
    is_return = len(quotes) > 1 or len(quotes[0]["legs"]) > 1
    amount = apply_markup(supplier_total, "flight")
    title = f"{origin['city'] or city_of(origin['code'])} ({origin['code']}) {'⇄' if is_return else '→'} {dest['city'] or city_of(dest['code'])} ({dest['code']})"
    subtitle = f"{seg0['airline_name']} {seg0['airline_code']}-{seg0['flight_number']} · {len(pax)} traveller{'s' if len(pax) > 1 else ''}"
    last_leg = quotes[-1]["legs"][-1]

    booking = SupplierBooking(
        customer_id=user.id, product="flight", status=SupplierBookingStatus.PENDING,
        title=title, subtitle=subtitle,
        travel_date=(first_leg["departure"] or "")[:10],
        end_date=(last_leg["departure"] or "")[:10] if is_return else None,
        currency=quotes[0]["currency"], amount=amount, supplier_amount=supplier_total,
        contact_name=payload.contact.name or f"{pax[0]['first_name']} {pax[0]['last_name']}",
        contact_email=payload.contact.email, contact_phone=payload.contact.phone,
        request_json=_dump({"trace_id": payload.trace_id, "legs": legs}),
        summary_json=_dump({"quotes": quotes, "passengers": pax,
                            "price_changed": any(q["is_price_changed"] for q in quotes)}),
        payment_status=PaymentStatus.UNPAID,
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)
    return SupplierBookingOut.from_model(booking)


def _check_pax_counts(raw: dict, pax: List[dict]):
    expected = {fb.get("PassengerType"): fb.get("PassengerCount") for fb in raw.get("FareBreakdown") or []}
    got = {t: sum(1 for p in pax if p["pax_type"] == t) for t in (1, 2, 3)}
    for t in (1, 2, 3):
        if (expected.get(t) or 0) != got[t]:
            raise HTTPException(status_code=422, detail="Traveller details don't match the number of adults/children/infants searched.")


# ================================================================== HOTELS

@hotels_router.get("/countries", summary="Country list (TBO static data)")
async def hotel_countries():
    try:
        return await tbo_hotels.countries()
    except tbo_client.TBOError as e:
        raise tbo_call_error(e)


@hotels_router.get("/cities", summary="City autocomplete (TBO CityList)")
async def hotel_cities(q: str = Query("", max_length=60), country: str = Query("IN", min_length=2, max_length=2)):
    try:
        return await tbo_hotels.search_cities(q, country.upper())
    except tbo_client.TBOError as e:
        raise tbo_call_error(e)


@hotels_router.post("/search", summary="Search hotels in a city (TBO Search over the city's hotel codes)")
async def hotel_search(payload: HotelSearchRequest):
    try:
        return await tbo_hotels.search(
            city_code=payload.city_code, check_in=payload.check_in.isoformat(), check_out=payload.check_out.isoformat(),
            rooms=[r.model_dump() for r in payload.rooms], nationality=payload.nationality.upper(),
            refundable_only=payload.refundable_only, meal_type=payload.meal_type, star_rating=payload.star_rating,
        )
    except tbo_client.TBOError as e:
        raise tbo_call_error(e)


@hotels_router.post("/rooms", summary="Live room options for one hotel (TBO Search, detailed)")
async def hotel_rooms(payload: HotelRoomsRequest):
    try:
        return await tbo_hotels.rooms(
            hotel_code=payload.hotel_code, check_in=payload.check_in.isoformat(), check_out=payload.check_out.isoformat(),
            rooms=[r.model_dump() for r in payload.rooms], nationality=payload.nationality.upper(),
        )
    except tbo_client.TBOError as e:
        raise tbo_call_error(e)


@hotels_router.get("/{hotel_code}/details", summary="Hotel content — images, facilities (TBO Hoteldetails)")
async def hotel_detail(hotel_code: str):
    try:
        d = (await tbo_hotels.hotel_details([hotel_code])).get(hotel_code)
    except tbo_client.TBOError as e:
        raise tbo_call_error(e)
    if not d:
        raise HTTPException(status_code=404, detail="Hotel not found.")
    return d


@hotels_router.post("/prebook", summary="Lock price & policies for a room (TBO PreBook)")
async def hotel_prebook(payload: PreBookRequest):
    try:
        return await tbo_hotels.prebook(payload.booking_code)
    except tbo_client.TBOError as e:
        raise tbo_call_error(e)


@hotels_router.post(
    "/bookings", response_model=SupplierBookingOut, status_code=201,
    summary="Create a hotel booking (Customer) — PreBook is re-run server side",
    dependencies=[Depends(require_booker)],
)
async def create_hotel_booking(payload: HotelBookingCreate, db: Session = Depends(get_db),
                               user: User = Depends(get_current_user)):
    try:
        pre = await tbo_hotels.prebook(payload.booking_code)
    except tbo_client.TBOError as e:
        raise tbo_call_error(e)
    if pre["validation"]["pan_mandatory"] and any(not g.pan for room in payload.guests for g in room[:1]):
        raise HTTPException(status_code=422, detail="PAN is required for the lead guest of each room for this hotel.")
    if pre["validation"]["passport_mandatory"] and any(not g.passport_no for room in payload.guests for g in room[:1]):
        raise HTTPException(status_code=422, detail="Passport number is required for the lead guest of each room.")

    details = {}
    try:
        details = (await tbo_hotels.hotel_details([payload.hotel_code])).get(payload.hotel_code) or {}
    except tbo_client.TBOError:
        pass

    room = pre["room"]
    guests = [[{**g.model_dump(), "email": payload.contact.email, "phone": payload.contact.phone} for g in r]
              for r in payload.guests]
    rooms_details = tbo_hotels.build_rooms_details(guests)
    nights = (payload.check_out - payload.check_in).days
    n_guests = sum(len(r) for r in payload.guests)
    lead = payload.guests[0][0]

    booking = SupplierBooking(
        customer_id=user.id, product="hotel", status=SupplierBookingStatus.PENDING,
        title=details.get("name") or payload.hotel_name or f"Hotel {payload.hotel_code}",
        subtitle=f"{room['name']} · {len(payload.rooms)} room{'s' if len(payload.rooms) > 1 else ''}, "
                 f"{n_guests} guest{'s' if n_guests > 1 else ''}, {nights} night{'s' if nights > 1 else ''}",
        travel_date=payload.check_in.isoformat(), end_date=payload.check_out.isoformat(),
        currency=pre["currency"], amount=room["price"], supplier_amount=room["supplier_price"],
        contact_name=payload.contact.name or f"{lead.first_name} {lead.last_name}",
        contact_email=payload.contact.email, contact_phone=payload.contact.phone,
        request_json=_dump({"booking_code": payload.booking_code, "nationality": payload.nationality.upper(),
                            "net_amount": room["net_amount"] or room["supplier_price"], "rooms_details": rooms_details}),
        summary_json=_dump({"hotel": {k: details.get(k) for k in ("hotel_code", "name", "address", "city", "star_rating",
                                                                 "image", "check_in_time", "check_out_time")},
                            "room": room, "rate_conditions": pre["rate_conditions"],
                            "guests": [[g.model_dump() for g in r] for r in payload.guests],
                            "nights": nights}),
        payment_status=PaymentStatus.UNPAID,
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)
    return SupplierBookingOut.from_model(booking)


# ================================================================== BOOKINGS

def _get_own(db: Session, booking_id: int, user: User) -> SupplierBooking:
    b = db.query(SupplierBooking).filter(SupplierBooking.id == booking_id).first()
    if not b:
        raise HTTPException(status_code=404, detail="Booking not found.")
    if b.customer_id != user.id and user.role not in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
        raise HTTPException(status_code=403, detail="You can only view your own bookings.")
    return b


@bookings_router.get("/my", response_model=List[SupplierBookingOut], summary="My bookings (Traveller / Agent)",
                     dependencies=[Depends(require_roles(UserRole.CUSTOMER, UserRole.AGENT))])
def my_travel_bookings(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (db.query(SupplierBooking).filter(SupplierBooking.customer_id == user.id)
            .order_by(SupplierBooking.created_at.desc()).all())
    return [SupplierBookingOut.from_model(b) for b in rows]


@bookings_router.get("/admin/all", response_model=List[AdminSupplierBookingOut], summary="All TBO bookings (Admin)",
                     dependencies=[Depends(require_roles(UserRole.ADMIN, UserRole.SUPER_ADMIN))])
def all_travel_bookings(db: Session = Depends(get_db)):
    rows = db.query(SupplierBooking).order_by(SupplierBooking.created_at.desc()).limit(500).all()
    return [AdminSupplierBookingOut.from_model(b) for b in rows]


@bookings_router.get("/{booking_id}", response_model=SupplierBookingOut, summary="Get one booking")
def get_travel_booking(booking_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return SupplierBookingOut.from_model(_get_own(db, booking_id, user))


@bookings_router.post(
    "/{booking_id}/pay", response_model=SupplierBookingOut,
    summary="Pay, then ticket (flight) / voucher (hotel) at TBO",
    description=("**Demo payment** — same test cards as the listings flow (`4242 4242 4242 4242` succeeds, "
                 "`4000 0000 0000 0002` declines). After a successful charge the booking is issued at TBO: "
                 "LCC flights → Ticket; GDS flights → Book + Ticket; hotels → Book (vouchered). "
                 "If TBO fails the payment is marked refunded. Replace with a real gateway before going live."),
    dependencies=[Depends(require_booker)],
)
async def pay_travel_booking(booking_id: int, payload: TravelPaymentRequest, request: Request,
                             db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    b = _get_own(db, booking_id, user)
    if b.payment_status == PaymentStatus.PAID:
        raise HTTPException(status_code=400, detail="This booking has already been paid for.")
    if b.status != SupplierBookingStatus.PENDING:
        raise HTTPException(status_code=400, detail="This booking can no longer be paid. Please search again.")

    card = payload.card_number.replace(" ", "")
    if len(card) < 12 or not card.isdigit():
        raise HTTPException(status_code=400, detail="Enter a valid card number.")
    b.payment_card_last4 = card[-4:]
    if card == "4000000000000002":
        b.payment_status = PaymentStatus.FAILED
        db.commit()
        raise HTTPException(status_code=402, detail="Your card was declined. Try test card 4242 4242 4242 4242 instead.")

    b.payment_status = PaymentStatus.PAID
    b.payment_reference = f"PAY-{secrets.token_hex(6).upper()}"
    b.paid_at = datetime.utcnow()
    db.commit()

    ip = end_user_ip(request)
    req = _load(b.request_json)
    try:
        if b.product == "flight":
            issued = []
            for leg in req["legs"]:
                issued.append(await tbo_flights.issue(req["trace_id"], leg["result_index"], leg["is_lcc"], leg["passengers"], ip))
            b.supplier_json = _dump({"tickets": issued})
            b.pnr = " / ".join(str(x["pnr"]) for x in issued if x.get("pnr"))
            b.supplier_booking_id = ",".join(str(x["booking_id"]) for x in issued if x.get("booking_id"))
        elif b.product == "hotel":
            res = await tbo_hotels.book(
                booking_code=req["booking_code"], nationality=req["nationality"], net_amount=req["net_amount"],
                rooms_details=req["rooms_details"], client_reference=f"SMT{b.id:07d}", end_user_ip=ip,
            )
            b.supplier_json = _dump(res)
            b.supplier_booking_id = str(res["booking_id"]) if res.get("booking_id") else None
            b.confirmation_no = res.get("confirmation_no")
            b.pnr = res.get("booking_ref_no")
        else:
            # Trains, buses, cabs, cruise, hajj & umrah, insurance, forex, visa, packages, activities
            try:
                res = await services_api.issue_booking(b)
            except ProviderError as pe:
                raise tbo_client.TBOError(pe.message, status_code=pe.status_code)
            b.supplier_json = _dump(res)
            b.pnr = res.get("reference")
            b.confirmation_no = res.get("reference")
            b.supplier_booking_id = res.get("supplier_booking_id")
        b.status = SupplierBookingStatus.CONFIRMED
        b.error_message = None
        db.add(Notification(user_id=user.id, title="Booking confirmed",
                            message=f"{b.title} is confirmed. Reference: {b.pnr or b.confirmation_no or b.payment_reference}"))
    except tbo_client.TBOError as e:
        partial = locals().get("issued") or []
        b.status = SupplierBookingStatus.FAILED
        b.payment_status = PaymentStatus.REFUNDED
        b.error_message = e.message
        if partial:
            b.supplier_json = _dump({"tickets": partial, "partial": True})
            b.pnr = " / ".join(str(x["pnr"]) for x in partial if x.get("pnr"))
            b.supplier_booking_id = ",".join(str(x["booking_id"]) for x in partial if x.get("booking_id"))
        db.add(Notification(user_id=user.id, title="Booking could not be completed",
                            message=f"{b.title}: {e.message} Your payment has been refunded."))
        db.commit()
        db.refresh(b)
        raise HTTPException(status_code=e.status_code if e.status_code != 502 else 502,
                            detail=f"{e.message} Your payment has been refunded.")
    db.commit()
    db.refresh(b)
    return SupplierBookingOut.from_model(b)


@bookings_router.post("/{booking_id}/cancel", response_model=SupplierBookingOut,
                      summary="Cancel — sends a cancellation request to TBO (SendChangeRequest)")
async def cancel_travel_booking(booking_id: int, payload: CancelRequest, request: Request,
                                db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    b = _get_own(db, booking_id, user)
    if b.status == SupplierBookingStatus.PENDING:
        b.status = SupplierBookingStatus.CANCELLED
        db.commit()
        db.refresh(b)
        return SupplierBookingOut.from_model(b)
    if b.status != SupplierBookingStatus.CONFIRMED or not b.supplier_booking_id:
        raise HTTPException(status_code=400, detail="Only confirmed bookings can be cancelled.")

    if b.product not in ("flight", "hotel"):
        try:
            res = await services_api.cancel_booking(b, payload.remarks or "Cancelled by customer")
        except ProviderError as pe:
            raise HTTPException(status_code=pe.status_code, detail=pe.message)
        done = res.get("status") == "cancelled"
        b.status = SupplierBookingStatus.CANCELLED if done else SupplierBookingStatus.CANCELLATION_REQUESTED
        if done and b.payment_status == PaymentStatus.PAID:
            b.payment_status = PaymentStatus.REFUNDED
        b.change_request_id = res.get("reference")
        db.add(Notification(user_id=b.customer_id, title="Booking cancelled" if done else "Cancellation requested",
                            message=f"{b.title}: " + ("cancelled. Refund as per the cancellation policy." if done
                                                      else "cancellation requested with the supplier.")))
        db.commit()
        db.refresh(b)
        return SupplierBookingOut.from_model(b)

    ip = end_user_ip(request)
    ids = []
    try:
        for sid in str(b.supplier_booking_id).split(","):
            fn = tbo_flights.cancel if b.product == "flight" else tbo_hotels.cancel
            res = await fn(int(sid), payload.remarks or "Cancelled by customer", ip)
            ids += [str(x) for x in res["change_request_ids"] if x]
    except tbo_client.TBOError as e:
        raise tbo_call_error(e)
    b.change_request_id = ",".join(ids)
    b.status = SupplierBookingStatus.CANCELLATION_REQUESTED
    db.add(Notification(user_id=b.customer_id, title="Cancellation requested",
                        message=f"We've asked the {'airline' if b.product == 'flight' else 'hotel'} to cancel {b.title}. "
                                "Refund (after supplier charges) will follow once it's processed."))
    db.commit()
    db.refresh(b)
    return SupplierBookingOut.from_model(b)


@bookings_router.post("/{booking_id}/refresh", response_model=SupplierBookingOut,
                      summary="Refresh status from TBO (GetBookingDetails / GetChangeRequestStatus)")
async def refresh_travel_booking(booking_id: int, request: Request, db: Session = Depends(get_db),
                                 user: User = Depends(get_current_user)):
    b = _get_own(db, booking_id, user)
    ip = end_user_ip(request)
    try:
        if b.status == SupplierBookingStatus.CANCELLATION_REQUESTED and b.change_request_id:
            fn = tbo_flights.change_request_status if b.product == "flight" else tbo_hotels.change_request_status
            done = True
            for cr in b.change_request_id.split(","):
                st = await fn(int(cr), ip)
                # Flight: 4 = Completed ; Hotel: 3 = Processed
                done = done and st.get("status") in (3, 4)
            if done:
                b.status = SupplierBookingStatus.CANCELLED
                b.payment_status = PaymentStatus.REFUNDED
    except tbo_client.TBOError as e:
        raise tbo_call_error(e)
    db.commit()
    db.refresh(b)
    return SupplierBookingOut.from_model(b)


# ================================================================== ADMIN

@admin_router.get("/status", summary="TBO connection status & agency balance (Admin)",
                  dependencies=[Depends(require_roles(UserRole.ADMIN, UserRole.SUPER_ADMIN))])
async def tbo_status():
    s = tbo_config.settings
    out = {"mode": s.mode, "flight_api": s.urls["air"], "hotel_api": s.urls["hotel_search"],
           "markup_percent": s.markup_percent, "balance": None, "error": None}
    try:
        bal = await tbo_client.shared("GetAgencyBalance", {})
        out["balance"] = {"cash": bal.get("CashBalance"), "credit": bal.get("CreditBalance")}
    except tbo_client.TBOError as e:
        out["error"] = e.message
    return out
