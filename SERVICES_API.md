# Connecting APIs for Trains, Buses, Cabs, Cruise, Hajj & Umrah, Insurance, Forex, Visa, Holidays, Activities

Flights and hotels use TBO (see `TBO_INTEGRATION.md`). Every other service runs through one common
flow, so **each new API is one backend file — the website does not change.**

```
Website (search form) ──► POST /api/services/{service}/search    ──► provider.search()
Pick an option        ──► POST /api/services/{service}/quote     ──► provider.quote()   (price + traveller form)
Traveller details     ──► POST /api/services/{service}/bookings  ──► provider.quote()   (re-price, saved as pending)
Pay                   ──► POST /api/travel-bookings/{id}/pay     ──► provider.book()    (ticket / voucher)
Cancel                ──► POST /api/travel-bookings/{id}/cancel  ──► provider.cancel()
```

Service keys: `train, bus, cab, cruise, hajj_umrah, travel_insurance, money_exchange, visa, package, activity`.

## Adding a real API (example: buses)

1. Copy `app/services/providers/example_http.py` → `app/services/providers/mybus.py`.
2. In `search / quote / book / cancel`, call the supplier and map its JSON to the normalised shapes
   documented at the top of `app/services/providers/base.py` (results, options, quote, booking).
   Put anything the supplier needs later (search key, fare id, session) in `token` — it never reaches the browser.
3. Register it in `app/services/providers/registry.py`:
   ```python
   from app.services.providers.mybus import MyBusProvider
   PROVIDERS["bus"]["mybus"] = lambda: MyBusProvider("bus")
   ```
4. In `.env`: `BUS_PROVIDER=mybus` (+ `BUS_API_URL`, `BUS_API_KEY` or whatever your adapter reads). Restart.

Admin → **API Bookings** shows which services are on sample data and which are live.

## Search parameters each page sends

| Service | params |
|---|---|
| train | from, to, date, travel_class (any/SL/3A/2A/1A/CC/2S), travellers, quota |
| bus | from, to, date, seats, bus_type |
| cab | trip_type, pickup, drop, date, time, car_type |
| cruise | port, destination, month (YYYY-MM), travellers, cabin |
| hajj_umrah | package, city, month, duration (nights), travellers |
| travel_insurance | trip_type, destination, start_date, end_date, travellers, max_age |
| money_exchange | product, currency, amount, city |
| visa | country, visa_type, date, travellers |
| package | destination, city, date, nights, travellers |
| activity | city, category, date, participants |

Traveller form fields come from your adapter's `quote()` → `traveller_fields`, so each supplier can ask for
exactly what it needs (passport, PAN, berth preference …).

## Who can book
- **Traveller** (customer) — books for themselves.
- **Travel Agent** — books for their customers once an admin approves the account (Admin → Users → Verify).
  Agents see all their bookings in the Agent dashboard.
- Distributor accounts are discontinued (new sign-ups are blocked).
