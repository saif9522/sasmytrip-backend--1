"""
Common contract every travel-service API adapter implements.

To plug in a real API for a service (e.g. a bus API):
  1. Copy app/services/providers/example_http.py to e.g. app/services/providers/mybus.py
  2. Implement search / quote / book / cancel by calling the supplier and
     returning the normalised dicts described below.
  3. Register it in app/services/providers/registry.py under PROVIDERS["bus"]["mybus"]
  4. Set BUS_PROVIDER=mybus in .env and restart. No frontend change is needed.

Normalised shapes
-----------------
Result (one search hit):
  {
    "id": str,                       # unique within this search
    "title": str,                    # "Rajdhani Express (12952)", "Volvo AC Sleeper — ABC Travels"
    "subtitle": str | None,
    "image": str | None,
    "rating": float | None,
    "badges": [str],                 # short chips: "Refundable", "Fastest"
    "start": {"time": ISO str | None, "place": str | None},
    "end":   {"time": ISO str | None, "place": str | None},
    "duration_min": int | None,
    "info": [{"label": str, "value": str}],   # key facts shown on the card
    "highlights": [str],                      # inclusions / features
    "tags": {str: str},                       # used for filters, e.g. {"Bus type": "AC Sleeper"}
    "options": [Option, ...],                 # at least one
    "token": any                              # anything the provider needs later (never sent to the browser)
  }

Option (what the customer actually buys — a class, a cabin, a plan ...):
  {"id": str, "name": str, "description": str | None, "price": float (TOTAL for the search's travellers),
   "currency": "INR", "available": int | None, "status_text": str | None,
   "refundable": bool, "cancellation": str | None, "token": any}

Quote (re-priced selection, returned before booking):
  {"price": float, "currency": str, "pax_count": int, "lead_only": bool,
   "traveller_fields": [{"key", "label", "type": text|number|date|select, "options"?: [...], "required": bool}],
   "terms": [str], "token": any}

Booking result:
  {"status": "confirmed" | "pending", "reference": str, "supplier_booking_id": str,
   "voucher": [{"label": str, "value": str}], "raw": any}

Cancel result:
  {"status": "cancelled" | "cancellation_requested", "refund_amount": float | None, "reference": str | None}
"""
from typing import Any, Dict, List


class ProviderError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ServiceProvider:
    """Base class — subclasses implement the four async methods."""
    service: str = ""
    name: str = "base"

    async def search(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        raise NotImplementedError

    async def quote(self, params: Dict[str, Any], result: Dict[str, Any], option: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    async def book(self, params: Dict[str, Any], result: Dict[str, Any], option: Dict[str, Any],
                   quote: Dict[str, Any], travellers: List[Dict[str, Any]], contact: Dict[str, Any],
                   client_reference: str) -> Dict[str, Any]:
        raise NotImplementedError

    async def cancel(self, booking: Dict[str, Any], remarks: str) -> Dict[str, Any]:
        raise NotImplementedError
