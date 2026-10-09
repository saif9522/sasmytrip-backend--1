"""
Mock TBO server — used when TBO_MODE=mock (default until credentials are set).

Responses mirror the JSON shape of TBO's documented samples so the real
normalisation code in flights.py / hotels.py runs unchanged. Data is
deterministic per route/date/city so the UI looks stable between refreshes.
"""
import hashlib
import random
import uuid
from datetime import datetime, timedelta

from app.services.tbo.airports import AIRPORTS

_AIRPORTS = {a[0]: a for a in AIRPORTS}
_RESULTS = {}   # ResultIndex -> raw result (so FareQuote/Book can find it)
_BOOKINGS = {}  # BookingId -> dict

AIRLINES = [
    ("6E", "IndiGo", True), ("AI", "Air India", False), ("SG", "SpiceJet", True),
    ("QP", "Akasa Air", True), ("IX", "Air India Express", True), ("EK", "Emirates", False),
]


def _rng(*parts) -> random.Random:
    seed = int(hashlib.md5("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)
    return random.Random(seed)


def _ok_envelope(**extra):
    return {"Response": {"ResponseStatus": 1, "Error": {"ErrorCode": 0, "ErrorMessage": ""}, **extra}}


def _airport(code):
    a = _AIRPORTS.get(code, (code, code, f"{code} Airport", "IN", "India"))
    return {"AirportCode": a[0], "AirportName": a[2], "Terminal": "1", "CityCode": a[0],
            "CityName": a[1], "CountryCode": a[3], "CountryName": a[4]}


def _make_leg(rng, origin, destination, day: datetime, airline, trip_indicator):
    stops = rng.choice([0, 0, 0, 1])
    dep = day.replace(hour=rng.choice([5, 6, 7, 9, 11, 13, 15, 17, 19, 21]), minute=rng.choice([0, 10, 25, 40, 55]))
    points = [origin] + (["HYD" if origin != "HYD" and destination != "HYD" else "BLR"] if stops else []) + [destination]
    segs = []
    t = dep
    for i in range(len(points) - 1):
        dur = rng.randint(70, 190)
        ground = 0 if i == 0 else rng.randint(50, 150)
        t = t + timedelta(minutes=ground)
        arr = t + timedelta(minutes=dur)
        segs.append({
            "Baggage": "15 KG", "CabinBaggage": "7 KG", "CabinClass": 2, "TripIndicator": trip_indicator,
            "SegmentIndicator": i + 1, "NoOfSeatAvailable": rng.randint(2, 9), "Duration": dur, "GroundTime": ground,
            "Craft": rng.choice(["320", "321", "738", "77W"]), "StopOver": False,
            "Airline": {"AirlineCode": airline[0], "AirlineName": airline[1],
                        "FlightNumber": str(rng.randint(100, 9999)), "FareClass": "R", "OperatingCarrier": ""},
            "Origin": {"Airport": _airport(points[i]), "DepTime": t.strftime("%Y-%m-%dT%H:%M:%S")},
            "Destination": {"Airport": _airport(points[i + 1]), "ArrTime": arr.strftime("%Y-%m-%dT%H:%M:%S")},
        })
        t = arr
    return segs


def _make_result(rng, trace, idx, segments_per_leg, airline, adults, children, infants):
    base_adult = rng.randint(2800, 9500) * len(segments_per_leg)
    tax_adult = rng.randint(700, 1400) * len(segments_per_leg)
    breakdown = [{"Currency": "INR", "PassengerType": 1, "PassengerCount": adults,
                  "BaseFare": base_adult * adults, "Tax": tax_adult * adults, "YQTax": 0,
                  "AdditionalTxnFeeOfrd": 0, "AdditionalTxnFeePub": 0, "PGCharge": 0}]
    if children:
        breakdown.append({"Currency": "INR", "PassengerType": 2, "PassengerCount": children,
                          "BaseFare": int(base_adult * 0.9) * children, "Tax": tax_adult * children, "YQTax": 0,
                          "AdditionalTxnFeeOfrd": 0, "AdditionalTxnFeePub": 0, "PGCharge": 0})
    if infants:
        breakdown.append({"Currency": "INR", "PassengerType": 3, "PassengerCount": infants,
                          "BaseFare": 1500 * infants, "Tax": 250 * infants, "YQTax": 0,
                          "AdditionalTxnFeeOfrd": 0, "AdditionalTxnFeePub": 0, "PGCharge": 0})
    base = sum(b["BaseFare"] for b in breakdown)
    tax = sum(b["Tax"] for b in breakdown)
    published = base + tax
    ri = f"OB{idx}-{trace[:6]}"
    result = {
        "ResultIndex": ri, "Source": 6, "IsLCC": airline[2], "IsRefundable": rng.random() > 0.3,
        "IsPassportRequiredAtBook": False, "IsPassportRequiredAtTicket": False,
        "IsPanRequiredAtBook": False, "IsPanRequiredAtTicket": False, "IsGSTMandatory": False,
        "AirlineRemark": "", "ResultFareType": rng.choice(["RegularFare", "RegularFare", "SME Fare"]),
        "Fare": {"Currency": "INR", "BaseFare": base, "Tax": tax, "YQTax": 0, "OtherCharges": 0, "Discount": 0,
                 "PublishedFare": published, "OfferedFare": round(published * 0.97, 2), "ServiceFee": 0,
                 "TdsOnCommission": 0, "TdsOnPLB": 0, "TdsOnIncentive": 0, "AdditionalTxnFeeOfrd": 0,
                 "AdditionalTxnFeePub": 0, "PGCharge": 0},
        "FareBreakdown": breakdown,
        "Segments": segments_per_leg,
        "LastTicketDate": None, "AirlineCode": airline[0], "ValidatingAirline": airline[0],
        "FareClassification": {"Type": "Publish"},
    }
    _RESULTS[ri] = result
    return result


def air(method: str, body: dict) -> dict:
    if method == "Search":
        segs = body["Segments"]
        adults, children, infants = body["AdultCount"], body.get("ChildCount", 0), body.get("InfantCount", 0)
        trace = uuid.uuid4().hex
        o, d = segs[0]["Origin"], segs[0]["Destination"]
        day = datetime.fromisoformat(segs[0]["PreferredDepartureTime"])
        international = _AIRPORTS.get(o, ("", "", "", "IN"))[3] != "IN" or _AIRPORTS.get(d, ("", "", "", "IN"))[3] != "IN"
        out_results, in_results = [], []
        idx = 0
        for n in range(14):
            rng = _rng(o, d, day.date(), n)
            airline = rng.choice(AIRLINES if international else AIRLINES[:5])
            legs = [_make_leg(rng, o, d, day, airline, 1)]
            if len(segs) > 1 and international:
                rday = datetime.fromisoformat(segs[1]["PreferredDepartureTime"])
                legs.append(_make_leg(rng, d, o, rday, airline, 2))
            if body.get("DirectFlight") and any(len(leg) > 1 for leg in legs):
                continue
            idx += 1
            out_results.append(_make_result(rng, trace, idx, legs, airline, adults, children, infants))
        if len(segs) > 1 and not international:
            rday = datetime.fromisoformat(segs[1]["PreferredDepartureTime"])
            for n in range(12):
                rng = _rng(d, o, rday.date(), n, "ib")
                airline = rng.choice(AIRLINES[:5])
                leg = _make_leg(rng, d, o, rday, airline, 2)
                if body.get("DirectFlight") and len(leg) > 1:
                    continue
                idx += 1
                r = _make_result(rng, trace, idx, [leg], airline, adults, children, infants)
                r["ResultIndex"] = r["ResultIndex"].replace("OB", "IB")
                _RESULTS[r["ResultIndex"]] = r
                in_results.append(r)
        results = [out_results] + ([in_results] if in_results else [])
        return _ok_envelope(TraceId=trace, Origin=o, Destination=d, Results=results)

    if method == "FareRule":
        return _ok_envelope(FareRules=[{
            "Origin": "", "Destination": "", "Airline": "",
            "FareBasisCode": "R0IP", "FareRestriction": "",
            "FareRuleDetail": ("<b>Cancellation:</b> ₹3,500 per passenger up to 4 hrs before departure.<br/>"
                               "<b>Date change:</b> ₹2,999 per passenger + fare difference.<br/>"
                               "<i>Sample fare rules (mock mode). Live rules come from the airline via TBO.</i>"),
        }])

    if method == "FareQuote":
        r = _RESULTS.get(body["ResultIndex"])
        if not r:
            return {"Response": {"ResponseStatus": 2, "Error": {"ErrorCode": 6, "ErrorMessage": "Your session (TraceId) is expired."}}}
        return _ok_envelope(IsPriceChanged=False, Results=r)

    if method == "SSR":
        return _ok_envelope(Baggage=[], MealDynamic=[], SeatDynamic=[])

    if method == "Book":
        bid = random.randint(1_000_000, 9_999_999)
        pnr = uuid.uuid4().hex[:6].upper()
        _BOOKINGS[bid] = {"pnr": pnr, "passengers": body["Passengers"]}
        return _ok_envelope(Response={"PNR": pnr, "BookingId": bid, "IsPriceChanged": False, "IsTimeChanged": False,
                                      "Status": 1, "FlightItinerary": {"PNR": pnr, "BookingId": bid}})

    if method == "Ticket":
        if "PNR" in body:
            bid, pnr = body["BookingId"], body["PNR"]
            pax = (_BOOKINGS.get(bid) or {}).get("passengers", [])
        else:
            bid, pnr = random.randint(1_000_000, 9_999_999), uuid.uuid4().hex[:6].upper()
            pax = body["Passengers"]
            _BOOKINGS[bid] = {"pnr": pnr, "passengers": pax}
        invoice = sum(float((p.get("Fare") or {}).get("PublishedFare") or 0) for p in pax)
        return _ok_envelope(Response={
            "PNR": pnr, "BookingId": bid, "IsPriceChanged": False, "IsTimeChanged": False, "TicketStatus": 1, "Status": 1,
            "FlightItinerary": {
                "PNR": pnr, "BookingId": bid, "Status": 5, "InvoiceNo": f"MOCK/{bid}", "InvoiceAmount": invoice,
                "Passenger": [{"Title": p["Title"], "FirstName": p["FirstName"], "LastName": p["LastName"],
                               "Ticket": {"TicketId": random.randint(100000, 999999),
                                          "TicketNumber": f"{random.randint(1000000000, 9999999999)}", "Status": "OK"}}
                              for p in pax],
            },
        })

    if method == "GetBookingDetails":
        b = _BOOKINGS.get(body.get("BookingId")) or {}
        return _ok_envelope(FlightItinerary={"PNR": b.get("pnr"), "BookingId": body.get("BookingId"), "Status": 5})

    if method == "SendChangeRequest":
        return _ok_envelope(TicketCRInfo=[{"ChangeRequestId": random.randint(10000, 99999), "Status": 1}])

    if method == "GetChangeRequestStatus":
        return _ok_envelope(ChangeRequestStatus=4, RefundedAmount=0, CancellationCharge=0)

    return {"Response": {"ResponseStatus": 2, "Error": {"ErrorCode": 99, "ErrorMessage": f"Mock: {method} not implemented"}}}


def shared(method: str, body: dict) -> dict:
    if method == "GetAgencyBalance":
        return {"Status": 1, "AgencyType": 1, "CashBalance": 250000.0, "CreditBalance": 0.0,
                "Error": {"ErrorCode": 0, "ErrorMessage": ""}}
    return {"Status": 1}


# ----------------------------------------------------------------- hotels

MOCK_CITIES = {
    "IN": [("130443", "Goa"), ("130452", "New Delhi"), ("144306", "Mumbai"), ("122175", "Jaipur"),
           ("111124", "Bangalore"), ("127343", "Manali"), ("145710", "Udaipur"), ("115936", "Kochi"),
           ("138673", "Srinagar"), ("100589", "Agra"), ("126632", "Hyderabad"), ("114107", "Chennai")],
    "AE": [("115936A", "Dubai"), ("100765", "Abu Dhabi")],
    "SA": [("118064", "Makkah"), ("124158", "Madinah")],
    "TH": [("101102", "Bangkok"), ("133123", "Phuket")],
    "SG": [("140024", "Singapore")],
}
COUNTRY_NAMES = {"IN": "India", "AE": "United Arab Emirates", "SA": "Saudi Arabia", "TH": "Thailand", "SG": "Singapore"}
HOTEL_WORDS = ["Grand", "Royal", "Palm", "Lotus", "Heritage", "Sea Breeze", "Orchid", "Residency", "Imperial", "Ivory",
               "Sapphire", "Lakeview", "Sunrise", "Crown", "Tulip"]
HOTEL_KINDS = ["Resort & Spa", "Hotel", "Suites", "Inn", "Palace", "Boutique Hotel"]
FACILITIES = ["Free WiFi", "Swimming pool", "Restaurant", "Room service", "Airport shuttle", "Fitness centre",
              "Spa", "Free parking", "Bar", "24-hour front desk", "Air conditioning", "Family rooms"]


def _city_name(code):
    for rows in MOCK_CITIES.values():
        for c, n in rows:
            if c == code:
                return n
    return "City"


def _mock_hotels(city_code):
    city = _city_name(city_code)
    out = []
    for i in range(18):
        rng = _rng("hotel", city_code, i)
        code = str(1000000 + int(hashlib.md5(f'{city_code}{i}'.encode()).hexdigest()[:5], 16))
        out.append({
            "HotelCode": code,
            "HotelName": f"{rng.choice(HOTEL_WORDS)} {city} {rng.choice(HOTEL_KINDS)}",
            "HotelRating": ["TwoStar", "ThreeStar", "ThreeStar", "FourStar", "FourStar", "FiveStar"][rng.randint(0, 5)],
            "Address": f"{rng.randint(1, 220)}, {rng.choice(['MG Road', 'Beach Road', 'Station Road', 'Lake Road', 'Mall Road'])}, {city}",
            "CityName": city,
            "Map": f"{15 + rng.random():.5f}|{73 + rng.random():.5f}",
            "HotelFacilities": rng.sample(FACILITIES, 6),
            "Description": f"A well-rated stay in {city} with comfortable rooms and friendly service.",
        })
    return out


_HOTEL_INDEX = {}  # code -> raw static row


def static(method: str, body: dict) -> dict:
    ok = {"Code": 200, "Description": "Success"}
    if method == "CountryList":
        return {"Status": ok, "CountryList": [{"Code": c, "Name": n} for c, n in COUNTRY_NAMES.items()]}
    if method == "CityList":
        cc = body.get("CountryCode", "IN")
        return {"Status": ok, "CityList": [{"Code": c, "Name": n} for c, n in MOCK_CITIES.get(cc, [])]}
    if method == "TBOHotelCodeList":
        hotels = _mock_hotels(body["CityCode"])
        for h in hotels:
            _HOTEL_INDEX[h["HotelCode"]] = h
        return {"Status": ok, "Hotels": hotels}
    if method == "Hoteldetails":
        out = []
        for code in str(body.get("Hotelcodes", "")).split(","):
            h = _HOTEL_INDEX.get(code)
            if not h:
                continue
            imgs = [f"https://picsum.photos/seed/tbo-{code}-{k}/800/500" for k in range(5)]
            out.append({**h, "Images": imgs, "Image": imgs[0], "HotelRating": {"TwoStar": 2, "ThreeStar": 3, "FourStar": 4, "FiveStar": 5}[h["HotelRating"]],
                        "CheckInTime": "2:00 PM", "CheckOutTime": "12:00 PM", "PhoneNumber": "+91 00000 00000",
                        "Attractions": [], "CountryName": "India", "PinCode": "000000"})
        return {"Status": ok, "HotelDetails": out}
    return {"Status": {"Code": 400, "Description": f"Mock: {method} not implemented"}}


_ROOM_BY_CODE = {}  # BookingCode -> raw room (for PreBook)

_ROOM_TYPES = ["Deluxe Room, 1 King Bed", "Superior Room, 2 Twin Beds", "Premium Room, Sea View",
               "Executive Suite", "Standard Room, 1 Queen Bed", "Family Room"]


def _mock_rooms(code, check_in, check_out, pax_rooms):
    nights = max((datetime.fromisoformat(check_out) - datetime.fromisoformat(check_in)).days, 1)
    rng = _rng("rooms", code, check_in)
    base = rng.randint(1800, 9000)
    rooms = []
    for k in range(rng.randint(2, 5)):
        nightly = base + k * rng.randint(400, 1800)
        total = nightly * nights * len(pax_rooms)
        refundable = rng.random() > 0.4
        meal = rng.choice(["Room_Only", "BreakFast", "Breakfast_For_2", "Half_Board"])
        ci = datetime.fromisoformat(check_in)
        rooms.append({
            "Name": [_ROOM_TYPES[(k + int(code) % 3) % len(_ROOM_TYPES)]] * len(pax_rooms),
            "BookingCode": f"{code}!TB!{k}!TB!{check_in}!TB!{uuid.uuid4().hex[:10]}",
            "Inclusion": "Free WiFi" + (", Breakfast" if "reak" in meal else ""),
            "DayRates": [[{"BasePrice": nightly * len(pax_rooms)} for _ in range(nights)]],
            "TotalFare": round(total * 1.12, 2), "TotalTax": round(total * 0.12, 2),
            "RoomPromotion": ["Member deal"] if k == 0 else [],
            "CancelPolicies": (
                [{"Index": "1", "FromDate": (ci - timedelta(days=10)).strftime("%d-%m-%Y 00:00:00"), "ChargeType": "Fixed", "CancellationCharge": 0},
                 {"Index": "2", "FromDate": (ci - timedelta(days=2)).strftime("%d-%m-%Y 00:00:00"), "ChargeType": "Percentage", "CancellationCharge": 100}]
                if refundable else
                [{"Index": "1", "FromDate": datetime.now().strftime("%d-%m-%Y 00:00:00"), "ChargeType": "Percentage", "CancellationCharge": 100}]
            ),
            "MealType": meal, "IsRefundable": refundable, "WithTransfers": False, "Supplements": [],
        })
    for r in rooms:
        _ROOM_BY_CODE[r["BookingCode"]] = r
    return rooms


def hotel(method: str, body: dict) -> dict:
    ok = {"Code": 200, "Description": "Successful"}
    if method == "Search":
        results = []
        for code in body["HotelCodes"].split(","):
            if int(_rng("avail", code, body["CheckIn"]).random() * 10) < 2:
                continue  # some hotels sold out
            rooms = _mock_rooms(code, body["CheckIn"], body["CheckOut"], body["PaxRooms"])
            if body.get("Filters", {}).get("Refundable"):
                rooms = [r for r in rooms if r["IsRefundable"]]
            if rooms:
                results.append({"HotelCode": code, "Currency": "INR", "Rooms": rooms})
        if not results:
            return {"Status": {"Code": 201, "Description": "No Available rooms for given criteria"}}
        return {"Status": ok, "HotelResult": results}

    if method == "PreBook":
        room = _ROOM_BY_CODE.get(body["BookingCode"])
        if not room:
            return {"Status": {"Code": 201, "Description": "Room is no longer available. Please search again."}}
        code = body["BookingCode"].split("!TB!")[0]
        return {"Status": ok, "HotelResult": [{"HotelCode": code, "Currency": "INR", "Rooms": [{**room, "NetAmount": room["TotalFare"]}],
                                                "RateConditions": ["Check-in from 2 PM. Valid government photo ID required at check-in.",
                                                                   "Mock mode - sample rate conditions."]}],
                "ValidationInfo": {"PanMandatory": False, "PassportMandatory": False, "PanCountRequired": 0,
                                   "GSTAllowed": True, "CorporateBookingAllowed": False}}

    if method == "book":
        bid = random.randint(1_000_000, 9_999_999)
        return {"BookResult": {"VoucherStatus": True, "ResponseStatus": 1, "Error": {"ErrorCode": 0, "ErrorMessage": ""},
                               "TraceId": uuid.uuid4().hex, "Status": 1, "HotelBookingStatus": "Confirmed",
                               "InvoiceNumber": f"MH/{bid}", "ConfirmationNo": f"CNF{random.randint(100000, 999999)}",
                               "BookingRefNo": f"{random.randint(1000000, 9999999)}", "BookingId": bid,
                               "IsPriceChanged": False, "IsCancellationPolicyChanged": False}}
    if method == "Getbookingdetail":
        return {"GetBookingDetailResult": {"ResponseStatus": 1, "Error": {"ErrorCode": 0}, "Status": 1,
                                           "HotelBookingStatus": "Confirmed", "BookingId": body.get("BookingId"), "VoucherStatus": True}}
    if method == "SendChangeRequest":
        return {"HotelChangeRequestResult": {"ResponseStatus": 1, "Error": {"ErrorCode": 0}, "ChangeRequestId": random.randint(1000, 9999),
                                             "ChangeRequestStatus": 1}}
    if method == "GetChangeRequestStatus":
        return {"HotelChangeRequestStatusResult": {"ResponseStatus": 1, "Error": {"ErrorCode": 0}, "ChangeRequestStatus": 3,
                                                   "RefundedAmount": 0, "CancellationCharge": 0}}
    return {"Status": {"Code": 400, "Description": f"Mock: {method} not implemented"}}
