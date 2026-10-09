"""
One API for every non-flight/hotel service (trains, buses, cabs, cruise, hajj & umrah,
travel insurance, money exchange, visa, holiday packages, activities).

  GET  /api/services/status                 which provider (mock / real) serves each service
  POST /api/services/{service}/search       {"params": {...}}  -> results
  POST /api/services/{service}/quote        {"search_id", "result_id", "option_id"} -> price + traveller form
  POST /api/services/{service}/bookings     customer — creates a pending booking (pay via /api/travel-bookings/{id}/pay)

Payment, cancellation and "my bookings" reuse /api/travel-bookings/* (same as flights & hotels).
"""
import json
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.core.security import get_current_user, require_booker, require_roles
from app.database import get_db
from app.models.models import PaymentStatus, SupplierBooking, SupplierBookingStatus, User, UserRole
from app.schemas.travel import SupplierBookingOut
from app.services.providers.base import ProviderError
from app.services.providers.registry import SERVICES, get_provider, provider_name
from app.services.tbo.config import apply_markup

router = APIRouter(prefix="/api/services", tags=["Trains, Buses, Cabs & other services (API)"])

_SEARCHES: Dict[str, Dict[str, Any]] = {}
TTL = 30 * 60


def _gc():
    now = time.time()
    for k in [k for k, v in _SEARCHES.items() if v["expires"] < now]:
        _SEARCHES.pop(k, None)


def _svc(service: str):
    if service not in SERVICES:
        raise HTTPException(status_code=404, detail="Unknown service.")


def _public(result: dict, service: str) -> dict:
    """Strip provider tokens and add selling prices (with markup)."""
    r = {k: v for k, v in result.items() if k != "token"}
    r["options"] = [{**{k: v for k, v in o.items() if k != "token"},
                     "supplier_price": o["price"], "price": apply_markup(o["price"], service)} for o in result["options"]]
    r["min_price"] = min((o["price"] for o in r["options"]), default=0)
    return r


def _lookup(search_id: str, result_id: str, option_id: str):
    s = _SEARCHES.get(search_id)
    if not s or s["expires"] < time.time():
        raise HTTPException(status_code=409, detail="These prices have expired. Please search again.")
    result = next((r for r in s["results"] if r["id"] == result_id), None)
    option = next((o for o in (result or {}).get("options", []) if o["id"] == option_id), None)
    if not result or not option:
        raise HTTPException(status_code=404, detail="That option is no longer available. Please search again.")
    return s, result, option


def _err(e: ProviderError):
    return HTTPException(status_code=e.status_code, detail=e.message)


class SearchIn(BaseModel):
    params: Dict[str, Any] = Field(default_factory=dict)


class QuoteIn(BaseModel):
    search_id: str
    result_id: str
    option_id: str


class ContactIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    email: EmailStr
    phone: str = Field(..., min_length=7, max_length=15)


class BookingIn(QuoteIn):
    travellers: List[Dict[str, Any]] = Field(..., min_length=1, max_length=30)
    contact: ContactIn


@router.get("/status", summary="Provider in use for each service")
def services_status():
    return {k: {"label": v, "provider": provider_name(k)} for k, v in SERVICES.items()}


@router.post("/{service}/search", summary="Search a service")
async def search(service: str, payload: SearchIn):
    _svc(service)
    _gc()
    params = {k: v for k, v in payload.params.items() if v not in (None, "")}
    try:
        results = await get_provider(service).search(params)
    except ProviderError as e:
        raise _err(e)
    sid = uuid.uuid4().hex
    _SEARCHES[sid] = {"service": service, "params": params, "results": results, "expires": time.time() + TTL}
    pub = [_public(r, service) for r in results]
    return {"search_id": sid, "service": service, "provider": provider_name(service), "params": params,
            "count": len(pub), "results": sorted(pub, key=lambda r: r["min_price"])}


@router.post("/{service}/quote", summary="Re-price an option and get the traveller form")
async def quote(service: str, payload: QuoteIn):
    _svc(service)
    s, result, option = _lookup(payload.search_id, payload.result_id, payload.option_id)
    try:
        q = await get_provider(service).quote(s["params"], result, option)
    except ProviderError as e:
        raise _err(e)
    pub = _public({**result, "options": [option]}, service)
    return {"result": pub, "option": pub["options"][0], "params": s["params"],
            "price": apply_markup(q["price"], service), "supplier_price": q["price"], "currency": q.get("currency", "INR"),
            "price_changed": abs(q["price"] - option["price"]) > 1, "pax_count": q["pax_count"],
            "lead_only": q["lead_only"], "traveller_fields": q["traveller_fields"], "terms": q.get("terms", [])}


@router.post("/{service}/bookings", response_model=SupplierBookingOut, status_code=201,
             summary="Create a booking (Customer) — re-quoted server side, then pay via /api/travel-bookings/{id}/pay",
             dependencies=[Depends(require_booker)])
async def create_booking(service: str, payload: BookingIn, db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)):
    _svc(service)
    s, result, option = _lookup(payload.search_id, payload.result_id, payload.option_id)
    try:
        q = await get_provider(service).quote(s["params"], result, option)
    except ProviderError as e:
        raise _err(e)

    need = 1 if q["lead_only"] else q["pax_count"]
    if len(payload.travellers) != need:
        raise HTTPException(status_code=422, detail=f"Enter details for {need} traveller{'s' if need > 1 else ''}.")
    for i, t in enumerate(payload.travellers, start=1):
        for f in q["traveller_fields"]:
            if f.get("required") and not str(t.get(f["key"], "")).strip():
                raise HTTPException(status_code=422, detail=f"Traveller {i}: {f['label']} is required.")
    travellers = [{f["key"]: str(t.get(f["key"], "")).strip()[:200] for f in q["traveller_fields"]} for t in payload.travellers]

    pub = _public({**result, "options": [option]}, service)
    start_time = (result.get("start") or {}).get("time") or ""
    end_time = (result.get("end") or {}).get("time") or ""
    pax = q["pax_count"]
    booking = SupplierBooking(
        customer_id=user.id, supplier=provider_name(service), product=service, status=SupplierBookingStatus.PENDING,
        title=result["title"][:255],
        subtitle=f"{option['name']}{f' · {pax} traveller' + ('s' if pax > 1 else '') if not q['lead_only'] and pax else ''}"[:255],
        travel_date=start_time[:10] or s["params"].get("date") or s["params"].get("start_date"),
        end_date=end_time[:10] or None, currency=q.get("currency", "INR"),
        amount=apply_markup(q["price"], service), supplier_amount=q["price"],
        contact_name=payload.contact.name, contact_email=payload.contact.email, contact_phone=payload.contact.phone,
        request_json=json.dumps({"service": service, "params": s["params"], "result": result, "option": option,
                                 "quote": q, "travellers": travellers, "contact": payload.contact.model_dump()}, default=str),
        summary_json=json.dumps({"service": service, "service_label": SERVICES[service], "result": pub,
                                 "option": pub["options"][0], "travellers": travellers,
                                 "traveller_fields": q["traveller_fields"], "terms": q.get("terms", []),
                                 "params": s["params"]}, default=str),
        payment_status=PaymentStatus.UNPAID,
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)
    return SupplierBookingOut.from_model(booking)


# ---- used by app/routers/travel.py for pay / cancel -------------------------------------------

async def issue_booking(b: SupplierBooking) -> dict:
    req = json.loads(b.request_json)
    prov = get_provider(b.product)
    res = await prov.book(req["params"], req["result"], req["option"], req["quote"], req["travellers"],
                          req["contact"], client_reference=f"SMT{b.id:07d}")
    return res


async def cancel_booking(b: SupplierBooking, remarks: str) -> dict:
    sup = json.loads(b.supplier_json) if b.supplier_json else {}
    return await get_provider(b.product).cancel(
        {"reference": b.pnr, "supplier_booking_id": b.supplier_booking_id, "raw": sup.get("raw")}, remarks)
