# TBO Flight + Hotel API — SaSmyTrip integration

Live flights and hotels on sasmytrip.com now come from the **TBO (tbo.com) Air API V10 and Hotel API V10**.
Partner listings (added by Agents/Distributors) still work and are at `/hotels/partners` and `/flights/partners`.

## 1. Run it today (no TBO account needed)

With no TBO credentials the backend runs in **mock mode**: it answers with sample data in TBO's exact JSON
format, so the whole website (search → book → pay → e-ticket/voucher → cancel) works end to end.

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload        # GET / shows "tbo_mode": "mock"
```

## 2. Switch to TBO test (staging) once TBO sends credentials

Put these in `.env` and restart the backend:

```
TBO_MODE=test
TBO_CLIENT_ID=ApiIntegrationNew
TBO_USERNAME=<API user from TBO mail>
TBO_PASSWORD=<API password, not the portal password>
TBO_END_USER_IP=<public IP of your server>
TBO_STATIC_USERNAME=TBOStaticAPITest
TBO_STATIC_PASSWORD=<password shown on TBO's Hotel "Authorization" doc page>
# only if TBO gives separate hotel credentials:
TBO_HOTEL_USERNAME=
TBO_HOTEL_PASSWORD=
```

## 3. Go live (after TBO certification)

```
TBO_MODE=live
TBO_USERNAME / TBO_PASSWORD   = live credentials
TBO_END_USER_IP               = your server's public IP (TBO whitelists it)
```
Default live URLs are built in (`app/services/tbo/config.py`). **If TBO's go-live mail lists different URLs,
paste them into `TBO_SHARED_URL`, `TBO_AIR_URL`, `TBO_HOTEL_SEARCH_URL`, `TBO_HOTEL_BOOK_URL`,
`TBO_HOTEL_STATIC_URL`** — no code change needed.

Your margin: `TBO_MARKUP_PERCENT`, `TBO_MARKUP_FLAT_FLIGHT`, `TBO_MARKUP_FLAT_HOTEL` (added on top of TBO's price).

> ⚠️ Before live: replace the demo card payment (`POST /api/travel-bookings/{id}/pay`) with a real
> gateway (Razorpay/Stripe). Today it accepts test cards only. In live mode a ticket is issued from your
> TBO wallet as soon as that endpoint succeeds.

## 4. How the TBO flows are mapped

| Website step | Our endpoint | TBO method |
|---|---|---|
| Login to TBO (cached for the day, auto-retry on expired session) | — | `SharedData/Authenticate` |
| Flight search (one-way, domestic return, international return) | `POST /api/flights/search` | `Search` |
| Fare rules tab | `POST /api/flights/fare-rule` | `FareRule` |
| Booking page re-prices the fare | `POST /api/flights/fare-quote` | `FareQuote` |
| Baggage/meal/seat options (API ready, not in UI yet) | `POST /api/flights/ssr` | `SSR` |
| Save travellers (fare re-quoted server-side) | `POST /api/flights/bookings` | `FareQuote` |
| Pay → issue ticket | `POST /api/travel-bookings/{id}/pay` | LCC: `Ticket` · GDS: `Book` + `Ticket` |
| Cancel | `POST /api/travel-bookings/{id}/cancel` | `SendChangeRequest` (RequestType 1) |
| Refund status | `POST /api/travel-bookings/{id}/refresh` | `GetChangeRequestStatus` |
| City autocomplete | `GET /api/hotels/cities` | `CityList` (cached 7 days) |
| Hotel search | `POST /api/hotels/search` | `TBOHotelCodeList` → `Search` (100 codes/call, parallel) → `Hoteldetails` |
| Rooms of one hotel | `POST /api/hotels/rooms` | `Search` (detailed) |
| Select room | `POST /api/hotels/prebook` | `PreBook` |
| Save guests (PreBook re-run) | `POST /api/hotels/bookings` | `PreBook` |
| Pay → voucher | `POST /api/travel-bookings/{id}/pay` | `Book` (IsVoucherBooking=true) |
| Cancel hotel | `POST /api/travel-bookings/{id}/cancel` | `SendChangeRequest` (RequestType 4) |
| Admin: mode + wallet balance | `GET /api/tbo/status` | `GetAgencyBalance` |

All endpoints are in Swagger at `/docs` under "Flights (TBO live)", "Hotels (TBO live)" and
"Flight & Hotel bookings (TBO)". Bookings are stored in the new `supplier_bookings` table
(created automatically; existing data is untouched).

## 5. TBO certification checklist

TBO asks for request/response logs of sample bookings before go-live. In test mode, run these from the
website. Set `TBO_LOG_DIR=logs/tbo` in `.env` and every TBO request + response is saved as a JSON file
there (password and TokenId masked) — zip that folder and send it to TBO:

1. Domestic one-way LCC (e.g. 6E) — 1 adult · and 2 adults + 1 child + 1 infant
2. Domestic one-way GDS/full-service (e.g. AI) — hold (`Book`) then `Ticket`
3. Domestic round trip (two separate results)
4. International round trip (combined result, passport details)
5. Flight cancellation (`SendChangeRequest`)
6. Hotel — 1 room 2 adults · 2 rooms with a child · cancellation

## 6. Files added / changed

**Backend**
- `app/services/tbo/` — `config.py`, `client.py`, `flights.py`, `hotels.py`, `airports.py`, `mock.py`
- `app/routers/travel.py`, `app/schemas/travel.py`
- `app/models/models.py` — `SupplierBooking` model
- `app/main.py` — loads `.env` (it wasn't being loaded before), registers routers
- `requirements.txt` — `httpx`

**Frontend**
- `src/api/travel.js`, `src/components/travel/ui.jsx`
- `src/pages/Flights.jsx` (new live search), `FlightBooking.jsx`, `Hotels.jsx` (new live search),
  `HotelDetail.jsx`, `HotelBooking.jsx`, `TripDetail.jsx` (e-ticket / voucher)
- `src/pages/PartnerHotels.jsx` (old hotels page, now `/hotels/partners`)
- `App.jsx` (routes), `Home.jsx` (search widget opens live results), `Login.jsx` (returns to booking after login),
  `CustomerDashboard.jsx` (Flights & hotels list), `AdminDashboard.jsx` (TBO tab)
