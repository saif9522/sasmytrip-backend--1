"""
TBO Air API V10 — business logic + response normalisation.

Flow (as per TBO docs):
  Search -> (FareRule) -> FareQuote -> (SSR) -> [non-LCC: Book -> Ticket] | [LCC: Ticket]
  -> GetBookingDetails ; cancellation via SendChangeRequest / GetChangeRequestStatus
"""
from typing import List, Optional

from app.services.tbo import client
from app.services.tbo.airports import city_of, country_of
from app.services.tbo.config import apply_markup

CABIN_CLASSES = {"all": 1, "economy": 2, "premium_economy": 3, "business": 4, "premium_business": 5, "first": 6}
CABIN_NAMES = {1: "All", 2: "Economy", 3: "Premium Economy", 4: "Business", 5: "Premium Business", 6: "First"}
PAX_ADULT, PAX_CHILD, PAX_INFANT = 1, 2, 3
GENDER = {"male": 1, "female": 2}


# ------------------------------------------------------------------ search

async def search(*, origin: str, destination: str, depart_date: str, return_date: Optional[str],
                 adults: int, children: int, infants: int, cabin: str, direct_only: bool,
                 end_user_ip: Optional[str] = None) -> dict:
    cabin_code = CABIN_CLASSES.get(cabin, 2)
    segments = [_segment(origin, destination, depart_date, cabin_code)]
    if return_date:
        segments.append(_segment(destination, origin, return_date, cabin_code))

    payload = {
        "AdultCount": adults,
        "ChildCount": children,
        "InfantCount": infants,
        "DirectFlight": bool(direct_only),
        "OneStopFlight": False,
        "JourneyType": 2 if return_date else 1,
        "PreferredAirlines": None,
        "Segments": segments,
        "Sources": None,
    }
    resp = await client.air("Search", payload, end_user_ip)
    results = resp.get("Results") or []
    # Results is an array of arrays: [outbound] for one-way / international return
    # (combined itineraries), or [outbound, inbound] for domestic return.
    groups = [[normalize_result(r) for r in (grp or [])] for grp in results]
    outbound = groups[0] if groups else []
    inbound = groups[1] if len(groups) > 1 else None
    return {
        "trace_id": resp.get("TraceId"),
        "origin": resp.get("Origin", origin),
        "destination": resp.get("Destination", destination),
        "is_return": bool(return_date),
        # True when the outbound results already contain both directions (international return)
        "combined_return": bool(return_date) and inbound is None,
        "outbound": sorted(outbound, key=lambda x: x["price"]),
        "inbound": sorted(inbound, key=lambda x: x["price"]) if inbound is not None else None,
    }


def _segment(origin: str, destination: str, date: str, cabin_code: int) -> dict:
    ts = f"{date}T00:00:00"
    return {
        "Origin": origin.upper(), "Destination": destination.upper(),
        "FlightCabinClass": cabin_code,
        "PreferredDepartureTime": ts, "PreferredArrivalTime": ts,
    }


# ------------------------------------------------------------------ normalisation

def normalize_result(r: dict) -> dict:
    fare = r.get("Fare") or {}
    legs = []
    for leg in r.get("Segments") or []:
        segs = [_norm_segment(s) for s in (leg or [])]
        if not segs:
            continue
        duration = 0
        for s in segs:
            duration += (s["duration"] or 0) + (s["ground_time"] or 0)
        acc = (leg[-1] or {}).get("AccumulatedDuration")
        legs.append({
            "origin": segs[0]["origin"],
            "destination": segs[-1]["destination"],
            "departure": segs[0]["origin"]["time"],
            "arrival": segs[-1]["destination"]["time"],
            "duration": acc or duration,
            "stops": len(segs) - 1,
            "segments": segs,
        })
    first = legs[0]["segments"][0] if legs else {}
    published = float(fare.get("PublishedFare") or 0)
    return {
        "result_index": r.get("ResultIndex"),
        "is_lcc": bool(r.get("IsLCC")),
        "is_refundable": bool(r.get("IsRefundable")),
        "source": r.get("Source"),
        "airline_code": r.get("AirlineCode") or first.get("airline_code"),
        "airline_name": first.get("airline_name"),
        "validating_airline": r.get("ValidatingAirline"),
        "fare_type": r.get("ResultFareType") or (r.get("FareClassification") or {}).get("Type"),
        "currency": fare.get("Currency", "INR"),
        "price": apply_markup(published, "flight"),           # what the customer pays
        "supplier_price": published,                           # TBO published fare
        "offered_fare": float(fare.get("OfferedFare") or 0),   # your net cost after commission
        "base_fare": float(fare.get("BaseFare") or 0),
        "taxes": round(published - float(fare.get("BaseFare") or 0), 2),
        "fare_breakdown": [
            {
                "pax_type": fb.get("PassengerType"),
                "count": fb.get("PassengerCount"),
                "base_fare": fb.get("BaseFare"),
                "tax": fb.get("Tax"),
            }
            for fb in (r.get("FareBreakdown") or [])
        ],
        "legs": legs,
        "last_ticket_date": r.get("LastTicketDate"),
        "requirements": {
            "passport_at_book": bool(r.get("IsPassportRequiredAtBook")),
            "passport_at_ticket": bool(r.get("IsPassportRequiredAtTicket")),
            "passport_full_details": bool(r.get("IsPassportFullDetailRequiredAtBook")),
            "pan_at_book": bool(r.get("IsPanRequiredAtBook")),
            "pan_at_ticket": bool(r.get("IsPanRequiredAtTicket")),
            "gst_mandatory": bool(r.get("IsGSTMandatory")),
        },
        "remark": r.get("AirlineRemark"),
    }


def _norm_segment(s: dict) -> dict:
    airline = s.get("Airline") or {}
    o = s.get("Origin") or {}
    d = s.get("Destination") or {}
    oa, da = o.get("Airport") or {}, d.get("Airport") or {}
    return {
        "airline_code": airline.get("AirlineCode"),
        "airline_name": airline.get("AirlineName"),
        "flight_number": airline.get("FlightNumber"),
        "fare_class": airline.get("FareClass"),
        "operating_carrier": airline.get("OperatingCarrier"),
        "origin": {
            "code": oa.get("AirportCode"), "name": oa.get("AirportName"), "terminal": oa.get("Terminal"),
            "city": oa.get("CityName"), "country": oa.get("CountryCode"), "time": o.get("DepTime"),
        },
        "destination": {
            "code": da.get("AirportCode"), "name": da.get("AirportName"), "terminal": da.get("Terminal"),
            "city": da.get("CityName"), "country": da.get("CountryCode"), "time": d.get("ArrTime"),
        },
        "duration": s.get("Duration"),
        "ground_time": s.get("GroundTime"),
        "baggage": s.get("Baggage"),
        "cabin_baggage": s.get("CabinBaggage"),
        "cabin_class": CABIN_NAMES.get(s.get("CabinClass"), s.get("CabinClass")),
        "seats_left": s.get("NoOfSeatAvailable"),
        "craft": s.get("Craft"),
    }


# ------------------------------------------------------------------ pre-booking

async def fare_rule(trace_id: str, result_index: str, end_user_ip=None) -> list:
    resp = await client.air("FareRule", {"TraceId": trace_id, "ResultIndex": result_index}, end_user_ip)
    return [
        {
            "origin": fr.get("Origin"), "destination": fr.get("Destination"), "airline": fr.get("Airline"),
            "fare_basis": fr.get("FareBasisCode"), "detail": fr.get("FareRuleDetail"),
            "restriction": fr.get("FareRestriction"),
        }
        for fr in (resp.get("FareRules") or [])
    ]


async def fare_quote_raw(trace_id: str, result_index: str, end_user_ip=None) -> dict:
    """Returns the raw TBO FareQuote `Results` object + IsPriceChanged."""
    resp = await client.air("FareQuote", {"TraceId": trace_id, "ResultIndex": result_index}, end_user_ip)
    results = resp.get("Results") or {}
    return {"raw": results, "is_price_changed": bool(resp.get("IsPriceChanged"))}


async def fare_quote(trace_id: str, result_index: str, end_user_ip=None) -> dict:
    q = await fare_quote_raw(trace_id, result_index, end_user_ip)
    out = normalize_result(q["raw"])
    out["is_price_changed"] = q["is_price_changed"]
    return out


async def ssr(trace_id: str, result_index: str, end_user_ip=None) -> dict:
    resp = await client.air("SSR", {"TraceId": trace_id, "ResultIndex": result_index}, end_user_ip)
    return {
        "baggage": resp.get("Baggage") or [],
        "meals": resp.get("MealDynamic") or resp.get("Meal") or [],
        "seats": resp.get("SeatDynamic") or [],
    }


# ------------------------------------------------------------------ booking

def build_passengers(passengers: List[dict], contact: dict, fq_raw: dict, origin: str, destination: str,
                     gst: Optional[dict] = None) -> List[dict]:
    """Converts our passenger form into TBO's Passenger[] including per-pax Fare."""
    breakdown = {fb.get("PassengerType"): fb for fb in (fq_raw.get("FareBreakdown") or [])}
    fare = fq_raw.get("Fare") or {}
    total_pax = max(len(passengers), 1)
    international = country_of(origin) != "IN" or country_of(destination) != "IN"

    def per_pax(pax_type: int) -> dict:
        fb = breakdown.get(pax_type) or {}
        n = max(int(fb.get("PassengerCount") or 1), 1)
        return {
            "Currency": fare.get("Currency", "INR"),
            "BaseFare": round(float(fb.get("BaseFare") or 0) / n, 2),
            "Tax": round(float(fb.get("Tax") or 0) / n, 2),
            "YQTax": round(float(fb.get("YQTax") or 0) / n, 2),
            "AdditionalTxnFeePub": round(float(fb.get("AdditionalTxnFeePub") or 0) / n, 2),
            "AdditionalTxnFeeOfrd": round(float(fb.get("AdditionalTxnFeeOfrd") or 0) / n, 2),
            "PGCharge": round(float(fb.get("PGCharge") or 0) / n, 2),
            "OtherCharges": round(float(fare.get("OtherCharges") or 0) / total_pax, 2),
            "Discount": round(float(fare.get("Discount") or 0) / total_pax, 2),
            "PublishedFare": round(float(fare.get("PublishedFare") or 0) / total_pax, 2),
            "OfferedFare": round(float(fare.get("OfferedFare") or 0) / total_pax, 2),
            "TdsOnCommission": round(float(fare.get("TdsOnCommission") or 0) / total_pax, 2),
            "TdsOnPLB": round(float(fare.get("TdsOnPLB") or 0) / total_pax, 2),
            "TdsOnIncentive": round(float(fare.get("TdsOnIncentive") or 0) / total_pax, 2),
            "ServiceFee": round(float(fare.get("ServiceFee") or 0) / total_pax, 2),
        }

    out = []
    for i, p in enumerate(passengers):
        pax_type = int(p.get("pax_type") or PAX_ADULT)
        dob = p.get("date_of_birth")
        nationality = (p.get("nationality") or "IN").upper()
        item = {
            "Title": p["title"],
            "FirstName": p["first_name"].strip(),
            "LastName": p["last_name"].strip(),
            "PaxType": pax_type,
            "DateOfBirth": f"{dob}T00:00:00" if dob else None,
            "Gender": GENDER.get((p.get("gender") or "male").lower(), 1),
            "PassportNo": p.get("passport_no") or "",
            "PassportExpiry": f"{p['passport_expiry']}T00:00:00" if p.get("passport_expiry") else None,
            "PassportIssueDate": f"{p['passport_issue_date']}T00:00:00" if p.get("passport_issue_date") else None,
            "AddressLine1": contact.get("address") or "India",
            "AddressLine2": "",
            "Fare": per_pax(pax_type),
            "City": contact.get("city") or city_of(origin),
            "CountryCode": nationality,
            "CountryName": "India" if nationality == "IN" else nationality,
            "Nationality": nationality,
            "CellCountryCode": contact.get("country_code") or "+91",
            "ContactNo": contact["phone"],
            "Email": contact["email"],
            "IsLeadPax": i == 0,
            "FFAirlineCode": None,
            "FFNumber": "",
            "GSTCompanyAddress": (gst or {}).get("address", ""),
            "GSTCompanyContactNumber": (gst or {}).get("phone", ""),
            "GSTCompanyName": (gst or {}).get("company_name", ""),
            "GSTNumber": (gst or {}).get("gst_number", ""),
            "GSTCompanyEmail": (gst or {}).get("email", ""),
        }
        if p.get("pan"):
            item["PAN"] = p["pan"]
        if not international and not item["PassportNo"]:
            item.pop("PassportExpiry", None)
            item.pop("PassportIssueDate", None)
        out.append(item)
    return out


async def issue(trace_id: str, result_index: str, is_lcc: bool, passengers: List[dict],
                end_user_ip=None) -> dict:
    """LCC: Ticket directly. Non-LCC: Book (hold PNR) then Ticket."""
    if is_lcc:
        resp = await client.air("Ticket", {
            "TraceId": trace_id, "ResultIndex": result_index, "Passengers": passengers,
            "PreferredCurrency": None, "AgentReferenceNo": "",
        }, end_user_ip)
        return _ticket_summary(resp)

    book = await client.air("Book", {"TraceId": trace_id, "ResultIndex": result_index, "Passengers": passengers}, end_user_ip)
    inner = book.get("Response") or {}
    if inner.get("IsPriceChanged") or inner.get("IsTimeChanged"):
        raise client.TBOError("The airline changed the fare/schedule while booking. Please search again.",
                              code="price_changed", status_code=409, raw=book)
    pnr, booking_id = inner.get("PNR"), inner.get("BookingId")
    resp = await client.air("Ticket", {"TraceId": trace_id, "PNR": pnr, "BookingId": booking_id}, end_user_ip)
    return _ticket_summary(resp, fallback_pnr=pnr, fallback_booking_id=booking_id)


def _ticket_summary(resp: dict, fallback_pnr=None, fallback_booking_id=None) -> dict:
    inner = resp.get("Response") or {}
    if inner.get("IsPriceChanged"):
        raise client.TBOError("The airline changed the fare while ticketing. Please search again.",
                              code="price_changed", status_code=409, raw=resp)
    itin = inner.get("FlightItinerary") or {}
    tickets = []
    for p in itin.get("Passenger") or []:
        t = p.get("Ticket") or {}
        tickets.append({
            "name": f"{p.get('Title', '')} {p.get('FirstName', '')} {p.get('LastName', '')}".strip(),
            "ticket_number": t.get("TicketNumber"), "ticket_id": t.get("TicketId"), "status": t.get("Status"),
        })
    return {
        "pnr": inner.get("PNR") or itin.get("PNR") or fallback_pnr,
        "booking_id": inner.get("BookingId") or itin.get("BookingId") or fallback_booking_id,
        "ticket_status": inner.get("TicketStatus"),
        "invoice_no": itin.get("InvoiceNo"),
        "invoice_amount": itin.get("InvoiceAmount"),
        "tickets": tickets,
    }


async def booking_details(booking_id: int, end_user_ip=None) -> dict:
    resp = await client.air("GetBookingDetails", {"BookingId": booking_id}, end_user_ip)
    itin = resp.get("FlightItinerary") or {}
    return {"pnr": itin.get("PNR"), "status": itin.get("Status"), "booking_id": itin.get("BookingId"),
            "invoice_no": itin.get("InvoiceNo"), "raw_status": itin.get("Status")}


async def cancel(booking_id: int, remarks: str, end_user_ip=None) -> dict:
    resp = await client.air("SendChangeRequest", {
        "BookingId": booking_id,
        "RequestType": 1,          # 1 = Full cancellation
        "CancellationType": 3,     # 3 = Others
        "Sectors": None,
        "TicketId": None,
        "Remarks": remarks or "Cancelled by customer",
    }, end_user_ip)
    crs = resp.get("TicketCRInfo") or []
    return {"change_request_ids": [c.get("ChangeRequestId") for c in crs],
            "statuses": [c.get("Status") for c in crs]}


async def change_request_status(change_request_id: int, end_user_ip=None) -> dict:
    resp = await client.air("GetChangeRequestStatus", {"ChangeRequestId": change_request_id}, end_user_ip)
    return {
        "status": resp.get("ChangeRequestStatus"),
        "refunded_amount": resp.get("RefundedAmount"),
        "cancellation_charge": resp.get("CancellationCharge"),
        "credit_note_no": resp.get("CreditNoteNo"),
    }
