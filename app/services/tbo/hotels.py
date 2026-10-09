"""
TBO Hotel API V10 — business logic + response normalisation.

Flow (as per TBO docs):
  Static: CountryList -> CityList -> TBOHotelCodeList -> Hoteldetails (cache these!)
  Dynamic: Search (HotelCodes, max 100 per call, run in parallel) -> PreBook -> Book
           -> Getbookingdetail ; cancellation via SendChangeRequest / GetChangeRequestStatus
"""
import asyncio
import time
import uuid
from datetime import date
from typing import Dict, List, Optional

from app.services.tbo import client
from app.services.tbo.config import apply_markup
from app.services.tbo import config

RATING_WORDS = {"OneStar": 1, "TwoStar": 2, "ThreeStar": 3, "FourStar": 4, "FiveStar": 5, "All": 0}
SEARCH_CHUNK = 100   # TBO recommends 100 hotel codes per Search request
DETAILS_CHUNK = 50


# ------------------------------------------------------------------ tiny TTL cache

class _TTLCache:
    def __init__(self):
        self._data: Dict[str, tuple] = {}

    def get(self, key):
        item = self._data.get(key)
        if item and item[0] > time.time():
            return item[1]
        self._data.pop(key, None)
        return None

    def set(self, key, value, ttl: int):
        self._data[key] = (time.time() + ttl, value)


_cache = _TTLCache()
DAY = 24 * 3600


def _ok(data: dict) -> bool:
    return ((data or {}).get("Status") or {}).get("Code") == 200


def _status_msg(data: dict) -> str:
    return ((data or {}).get("Status") or {}).get("Description") or "Supplier returned an error."


# ------------------------------------------------------------------ static data

async def countries() -> List[dict]:
    hit = _cache.get("countries")
    if hit is not None:
        return hit
    data = await client.hotel_static_api("CountryList", {})
    out = [{"code": c.get("Code"), "name": c.get("Name")} for c in data.get("CountryList") or []]
    _cache.set("countries", out, 7 * DAY)
    return out


async def cities(country_code: str) -> List[dict]:
    key = f"cities:{country_code}"
    hit = _cache.get(key)
    if hit is not None:
        return hit
    data = await client.hotel_static_api("CityList", {"CountryCode": country_code})
    out = []
    for c in data.get("CityList") or []:
        name = " ".join(str(c.get("Name") or "").split())  # TBO pads names with spaces
        out.append({"code": str(c.get("Code")), "name": name, "country_code": country_code})
    _cache.set(key, out, 7 * DAY)
    return out


async def search_cities(q: str, country_code: str = "IN", limit: int = 12) -> List[dict]:
    q = (q or "").strip().lower()
    rows = await cities(country_code)
    if not q:
        return rows[:limit]
    starts = [c for c in rows if c["name"].lower().startswith(q)]
    contains = [c for c in rows if q in c["name"].lower() and c not in starts]
    return (starts + contains)[:limit]


async def hotel_codes(city_code: str) -> List[dict]:
    key = f"codes:{city_code}"
    hit = _cache.get(key)
    if hit is not None:
        return hit
    data = await client.hotel_static_api("TBOHotelCodeList", {"CityCode": str(city_code), "IsDetailedResponse": "true"})
    out = []
    for h in data.get("Hotels") or []:
        lat, lng = _map(h.get("Map"))
        out.append({
            "hotel_code": str(h.get("HotelCode")),
            "name": h.get("HotelName"),
            "star_rating": _rating(h.get("HotelRating")),
            "address": h.get("Address"),
            "city": h.get("CityName"),
            "latitude": lat, "longitude": lng,
            "facilities": (h.get("HotelFacilities") or [])[:8],
        })
    _cache.set(key, out, DAY)
    return out


async def hotel_details(codes: List[str]) -> Dict[str, dict]:
    """Hoteldetails for many codes (cached individually)."""
    result, missing = {}, []
    for c in codes:
        hit = _cache.get(f"detail:{c}")
        if hit is not None:
            result[c] = hit
        else:
            missing.append(c)

    async def fetch(chunk):
        try:
            data = await client.hotel_static_api("Hoteldetails", {"Hotelcodes": ",".join(chunk), "Language": "EN"})
        except client.TBOError:
            return []
        return data.get("HotelDetails") or []

    chunks = [missing[i:i + DETAILS_CHUNK] for i in range(0, len(missing), DETAILS_CHUNK)]
    for rows in await asyncio.gather(*(fetch(c) for c in chunks)):
        for h in rows:
            d = _norm_details(h)
            _cache.set(f"detail:{d['hotel_code']}", d, DAY)
            result[d["hotel_code"]] = d
    return result


def _norm_details(h: dict) -> dict:
    lat, lng = _map(h.get("Map"))
    images = h.get("Images") or ([h["Image"]] if h.get("Image") else [])
    return {
        "hotel_code": str(h.get("HotelCode")),
        "name": h.get("HotelName"),
        "description": h.get("Description"),
        "star_rating": _rating(h.get("HotelRating")),
        "address": h.get("Address"),
        "city": h.get("CityName"),
        "country": h.get("CountryName"),
        "pin_code": h.get("PinCode"),
        "phone": h.get("PhoneNumber"),
        "latitude": lat, "longitude": lng,
        "facilities": h.get("HotelFacilities") or [],
        "attractions": h.get("Attractions") or [],
        "images": images,
        "image": images[0] if images else None,
        "check_in_time": h.get("CheckInTime"),
        "check_out_time": h.get("CheckOutTime"),
    }


def _rating(v) -> int:
    if isinstance(v, (int, float)):
        return int(v)
    return RATING_WORDS.get(str(v), 0)


def _map(v):
    try:
        lat, lng = str(v).split("|")
        return float(lat), float(lng)
    except Exception:
        return None, None


# ------------------------------------------------------------------ availability

def _search_payload(codes: List[str], check_in: str, check_out: str, rooms: List[dict], nationality: str,
                    detailed: bool, refundable_only: bool = False, meal_type: str = "All") -> dict:
    return {
        "CheckIn": check_in,
        "CheckOut": check_out,
        "HotelCodes": ",".join(codes),
        "GuestNationality": nationality,
        "PaxRooms": [
            {
                "Adults": r["adults"],
                "Children": r.get("children", 0),
                "ChildrenAges": r.get("children_ages") or ([] if not r.get("children") else [8] * r["children"]),
            }
            for r in rooms
        ],
        "ResponseTime": 23.0,
        "IsDetailedResponse": detailed,
        "Filters": {"Refundable": refundable_only, "NoOfRooms": 0, "MealType": meal_type or "All"},
    }


def _nights(check_in: str, check_out: str) -> int:
    return max((date.fromisoformat(check_out) - date.fromisoformat(check_in)).days, 1)


def norm_room(r: dict) -> dict:
    names = r.get("Name") or []
    total = float(r.get("TotalFare") or 0)
    return {
        "booking_code": r.get("BookingCode"),
        "names": names,
        "name": " + ".join(dict.fromkeys(names)) if names else "Room",
        "inclusion": r.get("Inclusion"),
        "meal_type": (r.get("MealType") or "").replace("_", " "),
        "is_refundable": bool(r.get("IsRefundable")),
        "supplier_price": total,
        "total_tax": float(r.get("TotalTax") or 0),
        "price": apply_markup(total, "hotel"),
        "recommended_selling_rate": r.get("RecommendedSellingRate"),
        "promotions": r.get("RoomPromotion") or [],
        "cancel_policies": [
            {"from_date": c.get("FromDate"), "charge_type": c.get("ChargeType"), "charge": c.get("CancellationCharge")}
            for c in (r.get("CancelPolicies") or [])
        ],
        "last_cancellation_deadline": r.get("LastCancellationDeadline"),
        "supplements": r.get("Supplements") or [],
        "day_rates": r.get("DayRates") or [],
    }


async def search(*, city_code: str, check_in: str, check_out: str, rooms: List[dict], nationality: str = "IN",
                 refundable_only: bool = False, meal_type: str = "All", star_rating: Optional[int] = None) -> dict:
    all_codes = await hotel_codes(city_code)
    static_by_code = {h["hotel_code"]: h for h in all_codes}
    if star_rating:
        all_codes = [h for h in all_codes if h["star_rating"] >= star_rating]
    codes = [h["hotel_code"] for h in all_codes][: config.settings.max_hotel_codes]
    if not codes:
        return {"search_id": uuid.uuid4().hex, "nights": _nights(check_in, check_out), "total_hotels": 0, "hotels": []}

    async def run(chunk):
        try:
            data = await client.hotel_search_api(
                "Search", _search_payload(chunk, check_in, check_out, rooms, nationality, False, refundable_only, meal_type)
            )
        except client.TBOError:
            return []
        return data.get("HotelResult") or [] if _ok(data) else []

    chunks = [codes[i:i + SEARCH_CHUNK] for i in range(0, len(codes), SEARCH_CHUNK)]
    results = [h for batch in await asyncio.gather(*(run(c) for c in chunks)) for h in batch]

    available_codes = [str(h.get("HotelCode")) for h in results]
    details = await hotel_details(available_codes)
    nights = _nights(check_in, check_out)

    hotels = []
    for h in results:
        code = str(h.get("HotelCode"))
        rooms_ = [norm_room(r) for r in (h.get("Rooms") or [])]
        if not rooms_:
            continue
        cheapest = min(rooms_, key=lambda r: r["price"])
        st = static_by_code.get(code, {})
        dt = details.get(code, {})
        hotels.append({
            "hotel_code": code,
            "name": dt.get("name") or st.get("name") or f"Hotel {code}",
            "star_rating": dt.get("star_rating") or st.get("star_rating") or 0,
            "address": dt.get("address") or st.get("address"),
            "city": dt.get("city") or st.get("city"),
            "image": dt.get("image"),
            "latitude": dt.get("latitude") or st.get("latitude"),
            "longitude": dt.get("longitude") or st.get("longitude"),
            "facilities": (dt.get("facilities") or st.get("facilities") or [])[:6],
            "currency": h.get("Currency", "INR"),
            "price": cheapest["price"],
            "price_per_night": round(cheapest["price"] / nights, 2),
            "supplier_price": cheapest["supplier_price"],
            "cheapest_room": cheapest["name"],
            "meal_type": cheapest["meal_type"],
            "free_cancellation": any(r["is_refundable"] for r in rooms_),
            "room_options": len(rooms_),
        })
    hotels.sort(key=lambda x: x["price"])
    return {"search_id": uuid.uuid4().hex, "nights": nights, "total_hotels": len(hotels), "hotels": hotels}


async def rooms(*, hotel_code: str, check_in: str, check_out: str, rooms: List[dict], nationality: str = "IN") -> dict:
    data = await client.hotel_search_api("Search", _search_payload([hotel_code], check_in, check_out, rooms, nationality, True))
    details = (await hotel_details([hotel_code])).get(hotel_code) or {}
    if not _ok(data) or not data.get("HotelResult"):
        return {"hotel": details, "rooms": [], "message": _status_msg(data)}
    h = data["HotelResult"][0]
    rms = sorted((norm_room(r) for r in h.get("Rooms") or []), key=lambda r: r["price"])
    return {"hotel": details, "currency": h.get("Currency", "INR"), "nights": _nights(check_in, check_out), "rooms": rms}


async def prebook(booking_code: str) -> dict:
    data = await client.hotel_search_api("PreBook", {"BookingCode": booking_code, "PaymentMode": "Limit"})
    if not _ok(data) or not data.get("HotelResult"):
        raise client.TBOError(_status_msg(data) or "This room is no longer available.", code="prebook", status_code=409, raw=data)
    h = data["HotelResult"][0]
    room_raw = (h.get("Rooms") or [{}])[0]
    room = norm_room(room_raw)
    room["net_amount"] = float(room_raw.get("NetAmount") or room_raw.get("TotalFare") or 0)
    v = data.get("ValidationInfo") or {}
    return {
        "hotel_code": str(h.get("HotelCode")),
        "currency": h.get("Currency", "INR"),
        "room": room,
        "rate_conditions": h.get("RateConditions") or [],
        "validation": {
            "pan_mandatory": bool(v.get("PanMandatory")),
            "passport_mandatory": bool(v.get("PassportMandatory")),
            "pan_count_required": v.get("PanCountRequired") or 0,
            "gst_allowed": bool(v.get("GSTAllowed")),
            "corporate_booking_allowed": bool(v.get("CorporateBookingAllowed")),
        },
    }


# ------------------------------------------------------------------ booking

def build_rooms_details(guests_per_room: List[List[dict]]) -> List[dict]:
    out = []
    for room in guests_per_room:
        pax = []
        for i, g in enumerate(room):
            pax.append({
                "Title": g["title"],
                "FirstName": g["first_name"].strip(),
                "MiddleName": "",
                "LastName": g["last_name"].strip(),
                "Email": g.get("email"),
                "PaxType": 2 if g.get("pax_type") == 2 else 1,
                "LeadPassenger": i == 0,
                "Age": int(g.get("age") or (30 if g.get("pax_type") != 2 else 8)),
                "PassportNo": g.get("passport_no"),
                "PassportIssueDate": None,
                "PassportExpDate": None,
                "Phoneno": g.get("phone"),
                "PaxId": 0,
                "GSTCompanyAddress": None,
                "GSTCompanyContactNumber": None,
                "GSTCompanyName": None,
                "GSTNumber": None,
                "GSTCompanyEmail": None,
                "PAN": g.get("pan"),
            })
        out.append({"HotelPassenger": pax})
    return out


async def book(*, booking_code: str, nationality: str, net_amount: float, rooms_details: List[dict],
               client_reference: str, end_user_ip=None) -> dict:
    res = await client.hotel_book_api("book", {
        "BookingCode": booking_code,
        "IsVoucherBooking": True,
        "GuestNationality": nationality,
        "RequestedBookingMode": 5,
        "NetAmount": net_amount,
        "ClientReferenceId": client_reference,
        "HotelRoomsDetails": rooms_details,
    }, "BookResult", end_user_ip)
    if res.get("IsPriceChanged") or res.get("IsCancellationPolicyChanged"):
        raise client.TBOError("The hotel changed the price or cancellation policy. Please re-check the room.",
                              code="price_changed", status_code=409, raw=res)
    if res.get("Status") not in (1, None) and not res.get("BookingId"):
        raise client.TBOError(res.get("HotelBookingStatus") or "Hotel booking failed.", code=res.get("Status"), raw=res)
    return {
        "booking_id": res.get("BookingId"),
        "confirmation_no": res.get("ConfirmationNo"),
        "booking_ref_no": res.get("BookingRefNo"),
        "status": res.get("HotelBookingStatus") or res.get("Status"),
        "voucher_status": res.get("VoucherStatus"),
        "invoice_number": res.get("InvoiceNumber"),
    }


async def booking_details(booking_id: int, end_user_ip=None) -> dict:
    res = await client.hotel_book_api("Getbookingdetail", {"BookingId": booking_id}, "GetBookingDetailResult", end_user_ip)
    return {"status": res.get("HotelBookingStatus") or res.get("Status"), "confirmation_no": res.get("ConfirmationNo"),
            "voucher_status": res.get("VoucherStatus"), "booking_id": res.get("BookingId")}


async def cancel(booking_id: int, remarks: str, end_user_ip=None) -> dict:
    res = await client.hotel_book_api("SendChangeRequest", {
        "BookingMode": 5, "RequestType": 4, "Remarks": remarks or "Cancelled by customer", "BookingId": booking_id,
    }, "HotelChangeRequestResult", end_user_ip)
    return {"change_request_ids": [res.get("ChangeRequestId")], "statuses": [res.get("ChangeRequestStatus")]}


async def change_request_status(change_request_id: int, end_user_ip=None) -> dict:
    res = await client.hotel_book_api("GetChangeRequestStatus", {"ChangeRequestId": change_request_id},
                                      "HotelChangeRequestStatusResult", end_user_ip)
    return {"status": res.get("ChangeRequestStatus"), "refunded_amount": res.get("RefundedAmount"),
            "cancellation_charge": res.get("CancellationCharge")}
