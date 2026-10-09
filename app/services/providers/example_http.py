"""
TEMPLATE — copy this file to connect a real supplier API to any service.

Every method must return the normalised dicts described in base.py. Map the
supplier's JSON onto those shapes; keep anything you need later (search keys,
fare ids, session tokens) in the "token" field of the result / option / quote
— it stays on the server and comes back to you in quote() and book().
"""
import os

import httpx

from app.services.providers.base import ProviderError, ServiceProvider


class ExampleHttpProvider(ServiceProvider):
    name = "example"

    def __init__(self, service: str):
        self.service = service
        prefix = service.upper()
        self.base_url = os.getenv(f"{prefix}_API_URL", "").rstrip("/")
        self.api_key = os.getenv(f"{prefix}_API_KEY", "")

    async def _post(self, path, payload):
        try:
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.post(f"{self.base_url}{path}", json=payload, headers={"Authorization": f"Bearer {self.api_key}"})
        except httpx.HTTPError as e:
            raise ProviderError(f"Supplier unreachable: {e.__class__.__name__}")
        if r.status_code >= 400:
            raise ProviderError(f"Supplier error {r.status_code}", 502)
        return r.json()

    async def search(self, params):
        data = await self._post("/search", params)            # <- supplier endpoint
        results = []
        for i, item in enumerate(data.get("items", [])):        # <- supplier field names
            results.append({
                "id": str(item.get("id", i)), "title": item.get("name"), "subtitle": item.get("type"),
                "image": item.get("image"), "rating": item.get("rating"), "badges": [],
                "start": {"time": item.get("departure"), "place": item.get("from")},
                "end": {"time": item.get("arrival"), "place": item.get("to")},
                "duration_min": item.get("duration"), "info": [], "highlights": [], "tags": {},
                "options": [{"id": str(o["id"]), "name": o["name"], "description": None, "price": float(o["price"]),
                             "currency": "INR", "available": o.get("seats"), "status_text": None,
                             "refundable": bool(o.get("refundable")), "cancellation": o.get("policy"),
                             "token": o.get("fare_key")} for o in item.get("fares", [])],
                "token": item.get("search_key"),
            })
        return results

    async def quote(self, params, result, option):
        data = await self._post("/quote", {"search_key": result["token"], "fare_key": option["token"]})
        return {"price": float(data["total"]), "currency": "INR", "pax_count": int(params.get("travellers", 1)),
                "lead_only": False, "traveller_fields": [
                    {"key": "name", "label": "Full name", "type": "text", "required": True},
                    {"key": "age", "label": "Age", "type": "number", "required": True}],
                "terms": data.get("terms", []), "token": data.get("quote_id")}

    async def book(self, params, result, option, quote, travellers, contact, client_reference):
        data = await self._post("/book", {"quote_id": quote["token"], "passengers": travellers,
                                           "contact": contact, "client_ref": client_reference})
        if data.get("status") != "CONFIRMED":
            raise ProviderError(data.get("message") or "Booking failed")
        return {"status": "confirmed", "reference": data["pnr"], "supplier_booking_id": str(data["booking_id"]),
                "voucher": [{"label": "PNR", "value": data["pnr"]}], "raw": data}

    async def cancel(self, booking, remarks):
        data = await self._post("/cancel", {"booking_id": booking["supplier_booking_id"], "reason": remarks})
        return {"status": "cancelled", "refund_amount": data.get("refund"), "reference": data.get("cancel_id")}
