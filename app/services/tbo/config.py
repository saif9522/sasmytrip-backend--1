"""
TBO (tbo.com / Tek Travels) API configuration.

Everything is driven by environment variables (see .env.example). Nothing is
hard-coded except TBO's published default endpoint URLs, and every one of
those can be overridden from the environment — TBO sends the exact LIVE URLs
in the go-live mail after certification, so paste them into the
TBO_*_URL variables at that point without touching code.

Modes
-----
TBO_MODE=mock  -> no network calls; realistic TBO-shaped sample data is served
                  so the whole website can be built/tested before credentials
                  arrive. (Default when no TBO_USERNAME is set.)
TBO_MODE=test  -> TBO staging / certification environment (tektravels.com).
TBO_MODE=live  -> production (travelboutiqueonline.com). Real tickets, real
                  money deducted from your TBO agency balance.
"""
import os
from dataclasses import dataclass, field


TEST_URLS = {
    # Shared services — Authenticate / Logout / GetAgencyBalance
    "shared": "http://Sharedapi.tektravels.com/SharedData.svc/rest",
    # Air API (Search, FareRule, FareQuote, SSR, Book, Ticket, GetBookingDetails, SendChangeRequest ...)
    "air": "http://api.tektravels.com/BookingEngineService_Air/AirService.svc/rest",
    # Hotel API V10 — Search & PreBook (Basic Auth with agency credentials)
    "hotel_search": "https://affiliate.tektravels.com/HotelAPI",
    # Hotel API V10 — Book, GetBookingDetail, SendChangeRequest (TokenId based)
    "hotel_book": "https://HotelBE.tektravels.com/hotelservice.svc/rest",
    # Hotel static content — CountryList, CityList, TBOHotelCodeList, Hoteldetails (Basic Auth, static credentials)
    "hotel_static": "http://api.tbotechnology.in/TBOHolidays_HotelAPI",
}

# Production endpoints. TBO confirms these in the go-live mail — if any differ,
# override them with the TBO_*_URL env vars instead of editing this file.
LIVE_URLS = {
    "shared": "https://api.travelboutiqueonline.com/SharedAPI/SharedData.svc/rest",
    "air": "https://booking.travelboutiqueonline.com/AirAPI_V10/AirService.svc/rest",
    "hotel_search": "https://affiliate.travelboutiqueonline.com/HotelAPI",
    "hotel_book": "https://hotelbooking.travelboutiqueonline.com/HotelAPI_V10/HotelService.svc/rest",
    "hotel_static": "https://api.tbotechnology.in/TBOHolidays_HotelAPI",
}


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _float(name: str, default: float = 0.0) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


@dataclass
class TBOSettings:
    mode: str
    client_id: str
    username: str
    password: str
    server_ip: str
    hotel_username: str
    hotel_password: str
    static_username: str
    static_password: str
    timeout: float
    markup_percent: float
    markup_flat_flight: float
    markup_flat_hotel: float
    max_hotel_codes: int
    urls: dict = field(default_factory=dict)

    @property
    def is_mock(self) -> bool:
        return self.mode == "mock"

    @property
    def is_live(self) -> bool:
        return self.mode == "live"


def load_settings() -> TBOSettings:
    username = os.getenv("TBO_USERNAME", "").strip()
    mode = os.getenv("TBO_MODE", "").strip().lower() or ("test" if username else "mock")
    if mode not in ("mock", "test", "live"):
        mode = "mock"

    base = dict(LIVE_URLS if mode == "live" else TEST_URLS)
    for key in base:
        override = os.getenv(f"TBO_{key.upper()}_URL", "").strip()
        if override:
            base[key] = override.rstrip("/")

    return TBOSettings(
        mode=mode,
        client_id=os.getenv("TBO_CLIENT_ID", "ApiIntegrationNew").strip(),
        username=username,
        password=os.getenv("TBO_PASSWORD", "").strip(),
        # Public IP of the server calling TBO (TBO whitelists it on live).
        server_ip=os.getenv("TBO_END_USER_IP", "127.0.0.1").strip(),
        # Hotel Search/PreBook use Basic Auth. TBO usually issues the same agency
        # API user for hotels — falls back to the flight credentials if not set.
        hotel_username=os.getenv("TBO_HOTEL_USERNAME", "").strip() or username,
        hotel_password=os.getenv("TBO_HOTEL_PASSWORD", "").strip() or os.getenv("TBO_PASSWORD", "").strip(),
        static_username=os.getenv("TBO_STATIC_USERNAME", "").strip(),
        static_password=os.getenv("TBO_STATIC_PASSWORD", "").strip(),
        timeout=_float("TBO_TIMEOUT_SECONDS", 60.0),
        markup_percent=_float("TBO_MARKUP_PERCENT", 0.0),
        markup_flat_flight=_float("TBO_MARKUP_FLAT_FLIGHT", 0.0),
        markup_flat_hotel=_float("TBO_MARKUP_FLAT_HOTEL", 0.0),
        max_hotel_codes=int(_float("TBO_MAX_HOTEL_CODES", 500)),
        urls=base,
    )


settings = load_settings()


def reload_settings() -> TBOSettings:
    """Used by tests to pick up env changes."""
    global settings
    settings = load_settings()
    return settings


def apply_markup(amount: float, product: str) -> float:
    """Your selling price = TBO price + % markup + flat markup (per booking)."""
    s = settings
    flat = s.markup_flat_flight if product == "flight" else s.markup_flat_hotel
    return round(float(amount or 0) * (1 + s.markup_percent / 100.0) + flat, 2)
