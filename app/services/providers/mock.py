"""
Mock provider: deterministic sample data for every service, in the normalised
format from base.py. Used until a real API is configured for that service.
"""
import hashlib
import random
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, List

from app.services.providers.base import ProviderError, ServiceProvider

PIC = "https://picsum.photos/seed/{}/480/320"


def rng_for(*parts) -> random.Random:
    return random.Random(int(hashlib.md5("|".join(map(str, parts)).encode()).hexdigest()[:8], 16))


def _d(s, default_days=7) -> date:
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return date.today() + timedelta(days=default_days)


def _month(s) -> date:
    try:
        y, m = str(s)[:7].split("-")
        return date(int(y), int(m), 1)
    except Exception:
        return (date.today() + timedelta(days=30)).replace(day=1)


def _n(v, default=1, lo=1, hi=50) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M")


def _opt(oid, name, price, **kw):
    return {"id": oid, "name": name, "description": kw.get("description"), "price": round(price, 2), "currency": "INR",
            "available": kw.get("available"), "status_text": kw.get("status_text"),
            "refundable": kw.get("refundable", True), "cancellation": kw.get("cancellation"), "token": None}


def _result(rid, title, options, **kw):
    return {"id": rid, "title": title, "subtitle": kw.get("subtitle"), "image": kw.get("image"),
            "rating": kw.get("rating"), "badges": kw.get("badges", []),
            "start": kw.get("start", {"time": None, "place": None}), "end": kw.get("end", {"time": None, "place": None}),
            "duration_min": kw.get("duration_min"), "info": kw.get("info", []), "highlights": kw.get("highlights", []),
            "tags": kw.get("tags", {}), "options": options, "token": None}


# ------------------------------------------------------------------ generators

def trains(p):
    frm, to, day = p.get("from") or "New Delhi (NDLS)", p.get("to") or "Mumbai Central (MMCT)", _d(p.get("date"))
    pax = _n(p.get("travellers"), 1, 1, 6)
    want = p.get("travel_class") or "any"
    names = ["Rajdhani Express", "Shatabdi Express", "Duronto Express", "Vande Bharat Express", "Superfast Express",
             "Garib Rath", "Sampark Kranti", "Mail Express"]
    classes = [("SL", "Sleeper", 1.0), ("3A", "AC 3 Tier", 2.6), ("2A", "AC 2 Tier", 3.7), ("1A", "AC First", 6.2),
               ("CC", "AC Chair Car", 2.2), ("2S", "Second Sitting", 0.55)]
    out = []
    for i in range(9):
        r = rng_for("train", frm, to, day, i)
        dep = datetime.combine(day, datetime.min.time()) + timedelta(hours=r.randint(4, 23), minutes=r.choice([0, 10, 25, 40, 55]))
        dur = r.randint(300, 1300)
        arr = dep + timedelta(minutes=dur)
        name = names[i % len(names)]
        number = str(r.randint(12001, 22999))
        base = r.randint(380, 720) * max(dur / 600, 0.6)
        chair = "Shatabdi" in name or "Vande" in name
        avail_classes = [c for c in classes if (c[0] in ("CC", "2S", "1A") if chair else c[0] not in ("CC", "2S"))]
        opts = []
        for code, label, mult in avail_classes:
            if want not in ("any", code):
                continue
            seats = r.choice([0, 0, 3, 12, 40, 87, 120])
            status = f"AVAILABLE {seats}" if seats else f"WL {r.randint(2, 60)}"
            opts.append(_opt(code, f"{label} ({code})", base * mult * pax, available=seats or None,
                             status_text=status, refundable=True, cancellation="As per railway rules"))
        if not opts:
            continue
        out.append(_result(
            f"T{number}", f"{name} ({number})", opts,
            subtitle="Runs daily" if r.random() > .4 else "Mon, Wed, Fri",
            start={"time": _iso(dep), "place": frm}, end={"time": _iso(arr), "place": to}, duration_min=dur,
            badges=(["Fastest"] if dur < 420 else []) + (["Pantry"] if r.random() > .5 else []),
            tags={"Train type": name.split()[0], "Departure": "Morning" if dep.hour < 12 else "Evening"},
            info=[{"label": "Train no.", "value": number}],
        ))
    return out


def buses(p):
    frm, to, day = p.get("from") or "Delhi", p.get("to") or "Jaipur", _d(p.get("date"))
    seats = _n(p.get("seats"), 1, 1, 10)
    want = p.get("bus_type") or "any"
    ops = ["Shree Travels", "Orange Tours", "City Link", "Royal Express", "State Transport (RSRTC)", "Zing Bus",
           "Night Rider", "GreenLine"]
    types = ["AC Sleeper", "AC Seater", "Volvo Multi-axle", "Non-AC Sleeper", "Non-AC Seater"]
    out = []
    for i in range(12):
        r = rng_for("bus", frm, to, day, i)
        bt = types[r.randint(0, len(types) - 1)]
        if want not in ("any", bt):
            continue
        dep = datetime.combine(day, datetime.min.time()) + timedelta(hours=r.choice([6, 8, 13, 18, 20, 21, 22, 23]), minutes=r.choice([0, 15, 30, 45]))
        dur = r.randint(240, 780)
        price = r.randint(450, 1600) * seats
        left = r.randint(2, 32)
        op = ops[i % len(ops)]
        out.append(_result(
            f"B{i}", f"{op}", [_opt("seat", f"{bt} seat" + ("s" if seats > 1 else ""), price, available=left,
                                    status_text=f"{left} seats left", cancellation="Free cancellation up to 12 hrs before departure")],
            subtitle=bt, rating=round(r.uniform(3.4, 4.8), 1),
            start={"time": _iso(dep), "place": f"{frm} — {r.choice(['ISBT', 'Main bus stand', 'Bypass pickup'])}"},
            end={"time": _iso(dep + timedelta(minutes=dur)), "place": f"{to} — {r.choice(['Bus stand', 'City centre'])}"},
            duration_min=dur, badges=(["Live tracking"] if r.random() > .5 else []) + (["Charging point"] if r.random() > .4 else []),
            tags={"Bus type": bt, "Operator": op}, info=[{"label": "Boarding points", "value": str(r.randint(2, 9))}],
        ))
    return out


def cabs(p):
    trip = p.get("trip_type") or "Outstation one-way"
    pickup, drop = p.get("pickup") or "Delhi", p.get("drop") or ""
    r0 = rng_for("cabdist", pickup, drop, trip)
    km = 40 if "Airport" in trip else 80 if "Hourly" in trip else r0.randint(150, 420)
    if "round" in trip.lower():
        km *= 2
    cars = [("Hatchback", "WagonR, Swift or similar", 4, 11), ("Sedan", "Dzire, Etios or similar", 4, 13),
            ("SUV", "Ertiga, Innova or similar", 6, 17), ("Innova Crysta", "Toyota Innova Crysta", 7, 21),
            ("Tempo Traveller", "12-seater", 12, 28), ("Luxury", "Mercedes E-Class or similar", 4, 45)]
    want = p.get("car_type") or "any"
    out = []
    for name, model, cap, per_km in cars:
        if want not in ("any", name):
            continue
        r = rng_for("cab", pickup, drop, name)
        fare = max(km * per_km, 900) + (300 if "Outstation" in trip else 0)
        out.append(_result(
            name.replace(" ", "_"), name, [_opt("fare", f"{trip} · all-inclusive", fare,
                                                cancellation="Free cancellation up to 6 hrs before pickup")],
            subtitle=model, image=PIC.format("smt-cab-" + name.replace(" ", "")), rating=round(r.uniform(4.0, 4.9), 1),
            start={"time": f"{p.get('date') or ''}T{p.get('time') or '09:00'}", "place": pickup},
            end={"time": None, "place": drop or None},
            info=[{"label": "Seats", "value": str(cap)}, {"label": "Included km", "value": f"{km} km"},
                  {"label": "Extra km", "value": f"₹{per_km}/km"}],
            highlights=["Driver allowance included", "Tolls & state tax included" if "Outstation" in trip else "Parking extra", "AC"],
            tags={"Seats": f"{cap} seats"}, badges=["Verified driver"] if r.random() > .3 else [],
        ))
    return out


def cruises(p):
    port = p.get("port") or "Mumbai"
    m = _month(p.get("month"))
    pax = _n(p.get("travellers"), 2, 1, 12)
    want = p.get("cabin") or "any"
    ships = ["Ocean Pearl", "Sea Voyager", "Coral Star", "Blue Horizon"]
    routes = {"Mumbai": [("Goa", 2), ("Lakshadweep", 4), ("Kochi", 3)], "Goa": [("Mumbai", 2), ("Lakshadweep", 3)],
              "Kochi": [("Lakshadweep", 3), ("Mumbai", 3)], "Chennai": [("Sri Lanka", 5), ("Visakhapatnam", 3)],
              "Singapore": [("Malaysia", 3), ("Thailand", 4)], "Dubai": [("Oman & Qatar", 4), ("Abu Dhabi", 2)]}
    dest_filter = (p.get("destination") or "").lower()
    out = []
    for i, (dest, nights) in enumerate(routes.get(port, routes["Mumbai"]) * 2):
        if dest_filter and dest_filter not in dest.lower():
            continue
        r = rng_for("cruise", port, m, i)
        sail = m + timedelta(days=r.randint(0, 25))
        cabins = [("interior", "Interior", 1.0), ("ocean_view", "Ocean view", 1.3), ("balcony", "Balcony", 1.7), ("suite", "Suite", 2.8)]
        base = r.randint(9000, 16000) * nights
        opts = [_opt(cid, label, base * mult * pax / 2 * (1 if pax <= 2 else 1.2), available=r.randint(0, 14) or None,
                     refundable=r.random() > .3, cancellation="50% refund up to 30 days before sailing")
                for cid, label, mult in cabins if want in ("any", cid)]
        if not opts:
            continue
        ship = ships[(i + r.randint(0, 3)) % len(ships)]
        start = datetime.combine(sail, datetime.min.time()) + timedelta(hours=17)
        out.append(_result(
            f"C{i}", f"{port} → {dest} → {port}", opts, subtitle=f"{ship} · {nights} nights",
            image=PIC.format(f"smt-cruise-{i}"), start={"time": _iso(start), "place": f"{port} port"},
            end={"time": _iso(start + timedelta(days=nights, hours=-9)), "place": f"{port} port"}, duration_min=nights * 1440,
            highlights=["All meals", "Live shows", "Pool & spa access", "Kids club"],
            tags={"Nights": f"{nights} nights", "Ship": ship}, info=[{"label": "Sails on", "value": sail.strftime("%d %b %Y")}],
        ))
    return out


def hajj_umrah(p):
    pkg = p.get("package") or "Umrah"
    city = p.get("city") or "Delhi"
    m = _month(p.get("month"))
    pax = _n(p.get("travellers"), 2, 1, 20)
    dur_want = p.get("duration") or "any"
    plans = [("Economy", 14, "1.5 km — shuttle", 3), ("Standard", 14, "700 m — walking", 3), ("Deluxe", 10, "300 m", 4),
             ("Premium", 10, "Haram view", 5), ("Express", 7, "500 m", 4), ("Extended", 21, "900 m — shuttle", 3)]
    out = []
    for i, (tier, nights, dist, stars) in enumerate(plans):
        if dur_want != "any" and str(nights) not in dur_want:
            continue
        r = rng_for("hu", pkg, city, m, i)
        base = (65000 if pkg != "Hajj" else 520000) * (1 + stars * 0.18) * (nights / 14) ** 0.5
        sharing = [("quad", "Quad sharing", 1.0), ("triple", "Triple sharing", 1.1), ("double", "Double sharing", 1.25)]
        start = datetime.combine(m + timedelta(days=r.randint(1, 25)), datetime.min.time()) + timedelta(hours=r.randint(2, 22))
        out.append(_result(
            f"HU{i}", f"{tier} {pkg} — {nights} nights", [_opt(sid, label, base * mult * pax, available=r.randint(2, 40),
                                                               refundable=False, cancellation="Non-refundable after visa is issued")
                                                          for sid, label, mult in sharing],
            subtitle=f"From {city} · {stars}★ hotels · {dist} from Haram", image=PIC.format(f"smt-hu-{i}"),
            start={"time": _iso(start), "place": city}, end={"time": _iso(start + timedelta(days=nights)), "place": city},
            duration_min=nights * 1440, highlights=["Return flights", "Visa", "Makkah & Madinah hotels", "Transfers", "Ziyarat"] + (["Meals"] if stars >= 4 else []),
            tags={"Hotel": f"{stars}★", "Duration": f"{nights} nights"},
            info=[{"label": "Makkah", "value": f"{nights * 2 // 3} nights"}, {"label": "Madinah", "value": f"{nights - nights * 2 // 3} nights"}],
            badges=["Group departure"] if r.random() > .5 else [],
        ))
    return out


def insurance(p):
    start, end = _d(p.get("start_date")), _d(p.get("end_date"), 14)
    days = max((end - start).days + 1, 1)
    pax = _n(p.get("travellers"), 1, 1, 10)
    age = _n(p.get("max_age"), 30, 0, 99)
    intl = (p.get("trip_type") or "International") != "Domestic"
    plans = [("Basic", 30000, 0.8), ("Standard", 50000, 1.0), ("Premium", 100000, 1.6), ("Elite", 250000, 2.4), ("Student Shield", 100000, 1.3)]
    insurers = ["Insurer A", "Insurer B", "Insurer C"]
    out = []
    for i, (plan, cover, mult) in enumerate(plans):
        r = rng_for("ins", p.get("destination"), days, i)
        prem = (42 if intl else 12) * days * mult * pax * (1.8 if age > 60 else 1)
        cur = "USD" if intl else "INR"
        out.append(_result(
            f"P{i}", f"{plan} plan", [_opt("plan", f"{plan} — {cur} {cover:,} cover", prem, refundable=True,
                                           cancellation="Full refund before the trip starts")],
            subtitle=insurers[i % 3], rating=round(r.uniform(4.0, 4.8), 1),
            info=[{"label": "Medical cover", "value": f"{cur} {cover:,}"}, {"label": "Trip", "value": f"{days} days"},
                  {"label": "Deductible", "value": f"{cur} {r.choice([0, 50, 100])}"}],
            highlights=["Medical emergencies", "Baggage loss", "Trip cancellation", "Passport loss"] + (["Adventure sports"] if mult > 1.5 else []),
            tags={"Cover": f"{cur} {cover:,}"}, badges=["Schengen approved"] if intl and cover >= 30000 else [],
        ))
    return out


def forex(p):
    cur = p.get("currency") or "USD"
    amt = float(p.get("amount") or 1000)
    product = p.get("product") or "Buy forex cash"
    base_rates = {"USD": 84.2, "EUR": 91.5, "GBP": 108.9, "AED": 22.95, "SAR": 22.45, "SGD": 64.8, "THB": 2.48,
                  "CAD": 61.6, "AUD": 55.4, "JPY": 0.56}
    rate = base_rates.get(cur, 80)
    sell = "Sell" in product
    out = []
    for i, (name, spread, delivery) in enumerate([("Partner A", 0.012, "Home delivery in 24 hrs"),
                                                  ("Partner B", 0.009, "Branch pickup today"),
                                                  ("Partner C", 0.015, "Home delivery in 48 hrs")]):
        r = (rate * (1 - spread)) if sell else (rate * (1 + spread))
        inr = amt * r
        fee = 0 if inr > 50000 else 149
        out.append(_result(
            f"FX{i}", f"{cur} {amt:,.0f} @ ₹{r:.2f}", [_opt("order", product, inr + (0 if sell else fee),
                                                              refundable=True, cancellation="Free cancellation before dispatch")],
            subtitle=name, info=[{"label": "Rate", "value": f"₹{r:.2f} per {cur}"}, {"label": "You " + ("get" if sell else "pay"), "value": f"₹{inr + (0 if sell else fee):,.0f}"},
                                  {"label": "Fee", "value": "Free" if not fee else f"₹{fee}"}],
            highlights=[delivery, "PAN & passport KYC"], tags={"Delivery": delivery.split(" in")[0]},
            badges=["Best rate"] if i == 1 else [],
        ))
    return out


def visas(p):
    country = (p.get("country") or "UAE").strip()
    vt = p.get("visa_type") or "Tourist"
    pax = _n(p.get("travellers"), 1, 1, 20)
    r0 = rng_for("visa", country.lower())
    products = [(f"{country} {vt} visa — 30 days, single entry", 30, "Single", r0.randint(5500, 9000), r0.randint(3, 6)),
                (f"{country} {vt} visa — 60 days, single entry", 60, "Single", r0.randint(9000, 14000), r0.randint(3, 6)),
                (f"{country} {vt} visa — 90 days, multiple entry", 90, "Multiple", r0.randint(14000, 26000), r0.randint(5, 10))]
    out = []
    for i, (title, stay, entry, fee, days) in enumerate(products):
        out.append(_result(
            f"V{i}", title, [_opt("normal", f"Standard processing · {days} working days", fee * pax,
                                  refundable=False, cancellation="Fee not refundable after submission"),
                             _opt("express", f"Express processing · {max(days - 2, 1)} working days", (fee + 2500) * pax,
                                  refundable=False, cancellation="Fee not refundable after submission")],
            subtitle=f"{vt} · e-Visa" if i < 2 else f"{vt} · sticker/e-Visa", image=PIC.format(f"smt-visa-{country.lower()}-{i}"),
            info=[{"label": "Stay", "value": f"{stay} days"}, {"label": "Entry", "value": entry}, {"label": "Validity", "value": f"{stay + 30} days"}],
            highlights=["Document check", "Form filling", "Status tracking"], tags={"Entry": entry},
        ))
    return out


def packages(p):
    dest = (p.get("destination") or "Kerala").strip()
    city = p.get("city") or "Delhi"
    start = _d(p.get("date"))
    pax = _n(p.get("travellers"), 2, 1, 30)
    want_n = p.get("nights") or "any"
    out = []
    for i, (nights, tier, stars) in enumerate([(3, "Getaway", 3), (4, "Classic", 3), (5, "Explorer", 4), (5, "Premium", 5), (6, "Grand", 4), (7, "Luxury", 5)]):
        if want_n != "any" and str(nights) != str(want_n):
            continue
        r = rng_for("pkg", dest.lower(), i)
        per = r.randint(9000, 16000) * nights * (1 + (stars - 3) * 0.35)
        opts = [_opt("with_flights", "With flights from " + city, (per + r.randint(9000, 16000)) * pax, refundable=True,
                     cancellation="Free cancellation up to 15 days before travel"),
                _opt("land_only", "Land only (no flights)", per * pax, refundable=True,
                     cancellation="Free cancellation up to 15 days before travel")]
        out.append(_result(
            f"PK{i}", f"{dest} {tier} — {nights}N/{nights + 1}D", opts, subtitle=f"{stars}★ hotels · departs from {city}",
            image=PIC.format(f"smt-pkg-{dest.lower()}-{i}"), rating=round(r.uniform(4.1, 4.9), 1),
            start={"time": _iso(datetime.combine(start, datetime.min.time())), "place": city},
            end={"time": _iso(datetime.combine(start + timedelta(days=nights), datetime.min.time())), "place": city},
            duration_min=nights * 1440,
            highlights=["Hotels", "Daily breakfast", "Sightseeing", "Airport transfers"] + (["All meals"] if stars == 5 else []),
            tags={"Hotel": f"{stars}★", "Duration": f"{nights} nights"},
            badges=["Best seller"] if i == 2 else [],
        ))
    return out


def activities(p):
    city = (p.get("city") or "Goa").strip()
    day = _d(p.get("date"))
    pax = _n(p.get("participants"), 2, 1, 30)
    cat = p.get("category") or "any"
    items = [("City sightseeing tour", "Sightseeing tour", 240, 900), ("Sunset cruise", "Water sports", 120, 1200),
             ("Scuba diving (beginner)", "Water sports", 180, 3500), ("Heritage walk", "Food & culture", 150, 600),
             ("Paragliding", "Adventure", 60, 2800), ("Theme park day ticket", "Theme park", 480, 1800),
             ("Desert safari with dinner", "Desert safari", 360, 2600), ("Street food tour", "Food & culture", 180, 1100)]
    out = []
    for i, (title, category, mins, price) in enumerate(items):
        if cat not in ("any", category):
            continue
        r = rng_for("act", city.lower(), i)
        slots = [("morning", "Morning slot · 9:00 AM"), ("afternoon", "Afternoon slot · 2:00 PM")]
        out.append(_result(
            f"A{i}", f"{title} — {city}", [_opt(sid, label, price * pax * r.uniform(0.9, 1.3), available=r.randint(2, 20),
                                                 cancellation="Free cancellation up to 24 hrs before")
                                            for sid, label in slots],
            subtitle=category, image=PIC.format(f"smt-act-{city.lower()}-{i}"), rating=round(r.uniform(4.0, 4.9), 1),
            duration_min=mins, start={"time": _iso(datetime.combine(day, datetime.min.time()) + timedelta(hours=9)), "place": city},
            highlights=["Instant confirmation", "Mobile voucher"] + (["Hotel pickup"] if r.random() > .4 else []),
            tags={"Category": category}, info=[{"label": "Duration", "value": f"{mins // 60}h {mins % 60:02d}m"}],
        ))
    return out


GENERATORS = {
    "train": trains, "bus": buses, "cab": cabs, "cruise": cruises, "hajj_umrah": hajj_umrah,
    "travel_insurance": insurance, "money_exchange": forex, "visa": visas, "package": packages, "activity": activities,
}

TEXT = {"type": "text", "required": True}
TRAVELLER_FIELDS = {
    "train": [dict(key="name", label="Full name", **TEXT), dict(key="age", label="Age", type="number", required=True),
              dict(key="gender", label="Gender", type="select", options=["Male", "Female", "Other"], required=True),
              dict(key="berth", label="Berth preference", type="select", options=["No preference", "Lower", "Middle", "Upper", "Side lower"], required=False)],
    "bus": [dict(key="name", label="Full name", **TEXT), dict(key="age", label="Age", type="number", required=True),
            dict(key="gender", label="Gender", type="select", options=["Male", "Female", "Other"], required=True)],
    "cab": [dict(key="name", label="Passenger name", **TEXT), dict(key="pickup_address", label="Exact pickup address", **TEXT)],
    "cruise": [dict(key="name", label="Full name (as on ID)", **TEXT), dict(key="dob", label="Date of birth", type="date", required=True),
               dict(key="gender", label="Gender", type="select", options=["Male", "Female", "Other"], required=True),
               dict(key="id_number", label="Passport / ID number", **TEXT)],
    "hajj_umrah": [dict(key="name", label="Full name (as on passport)", **TEXT), dict(key="gender", label="Gender", type="select", options=["Male", "Female"], required=True),
                   dict(key="dob", label="Date of birth", type="date", required=True), dict(key="passport_no", label="Passport number", **TEXT),
                   dict(key="passport_expiry", label="Passport expiry", type="date", required=True)],
    "travel_insurance": [dict(key="name", label="Full name", **TEXT), dict(key="dob", label="Date of birth", type="date", required=True),
                         dict(key="passport_no", label="Passport number", type="text", required=False),
                         dict(key="nominee", label="Nominee name", **TEXT)],
    "money_exchange": [dict(key="name", label="Full name (as on PAN)", **TEXT), dict(key="pan", label="PAN", **TEXT),
                       dict(key="passport_no", label="Passport number", **TEXT), dict(key="address", label="Delivery address", **TEXT)],
    "visa": [dict(key="name", label="Full name (as on passport)", **TEXT), dict(key="dob", label="Date of birth", type="date", required=True),
             dict(key="passport_no", label="Passport number", **TEXT), dict(key="passport_expiry", label="Passport expiry", type="date", required=True)],
    "package": [dict(key="name", label="Full name", **TEXT), dict(key="age", label="Age", type="number", required=True)],
    "activity": [dict(key="name", label="Lead guest name", **TEXT)],
}
LEAD_ONLY = {"cab", "money_exchange", "activity"}

TERMS = {
    "train": ["Tickets are subject to railway availability and rules.", "Waitlisted tickets are auto-cancelled if not confirmed at charting."],
    "visa": ["Approval is at the sole discretion of the embassy.", "Upload passport, photo and documents after booking."],
    "hajj_umrah": ["Passport must be valid for 6 months from travel.", "Package is non-refundable after visa issuance."],
}


class MockProvider(ServiceProvider):
    name = "mock"

    def __init__(self, service: str):
        self.service = service

    async def search(self, params):
        return GENERATORS[self.service](params)

    async def quote(self, params, result, option):
        from app.services.providers.registry import pax_count
        if option.get("available") == 0:
            raise ProviderError("This option just sold out. Please pick another.", 409)
        return {"price": option["price"], "currency": option.get("currency", "INR"),
                "pax_count": 1 if self.service in LEAD_ONLY else pax_count(self.service, params),
                "lead_only": self.service in LEAD_ONLY, "traveller_fields": TRAVELLER_FIELDS[self.service],
                "terms": TERMS.get(self.service, []) + ([option["cancellation"]] if option.get("cancellation") else []),
                "token": None}

    async def book(self, params, result, option, quote, travellers, contact, client_reference):
        ref = {"train": lambda: str(random.randint(2100000000, 8999999999)),
               }.get(self.service, lambda: uuid.uuid4().hex[:8].upper())()
        voucher = [{"label": "Booked", "value": option["name"]}]
        if self.service == "train":
            voucher += [{"label": "Coach / berth", "value": ", ".join(f"B{random.randint(1, 6)}-{random.randint(1, 72)}" for _ in travellers)}]
        if self.service == "bus":
            voucher += [{"label": "Seat numbers", "value": ", ".join(str(random.randint(1, 40)) for _ in travellers)}]
        if self.service == "cab":
            voucher += [{"label": "Driver details", "value": "Shared 2 hours before pickup"}]
        if self.service == "visa":
            voucher += [{"label": "Next step", "value": "Upload documents from the link sent to your email"}]
        return {"status": "confirmed", "reference": ref, "supplier_booking_id": f"MOCK-{uuid.uuid4().hex[:6].upper()}",
                "voucher": voucher, "raw": {"mock": True, "client_reference": client_reference}}

    async def cancel(self, booking, remarks):
        return {"status": "cancelled", "refund_amount": None, "reference": f"CXL-{uuid.uuid4().hex[:6].upper()}"}
