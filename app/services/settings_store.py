"""
Platform settings kept in the `app_settings` table and edited from Admin → Settings.
Values are cached in memory and refreshed every 60 s (and immediately after an update).
Defaults fall back to the .env values so nothing changes until an admin saves Settings.
"""
import os
import time
from typing import Dict

from app.database import SessionLocal


def _env(name, default="0"):
    return os.getenv(name, default)


# key -> (label, type, default, group)
SCHEMA = {
    "company_name": ("Company name", "text", "SaSmyTrip Travels Pvt. Ltd.", "Company"),
    "support_email": ("Support email", "text", "support@sasmytrip.com", "Company"),
    "support_phone": ("Support phone", "text", "", "Company"),
    "company_address": ("Office address", "text", "", "Company"),
    "gst_number": ("GSTIN", "text", "", "Company"),
    "markup_flight_percent": ("Flight markup %", "number", lambda: _env("TBO_MARKUP_PERCENT"), "Pricing"),
    "markup_flight_flat": ("Flight markup (flat ₹ per booking)", "number", lambda: _env("TBO_MARKUP_FLAT_FLIGHT"), "Pricing"),
    "markup_hotel_percent": ("Hotel markup %", "number", lambda: _env("TBO_MARKUP_PERCENT"), "Pricing"),
    "markup_hotel_flat": ("Hotel markup (flat ₹ per booking)", "number", lambda: _env("TBO_MARKUP_FLAT_HOTEL"), "Pricing"),
    "markup_services_percent": ("Other services markup % (trains, buses, visa …)", "number", lambda: _env("TBO_MARKUP_PERCENT"), "Pricing"),
    "agent_commission_percent": ("Default agent commission %", "number", "0", "Agents"),
    "agent_auto_approve": ("Auto-approve new agents", "bool", "false", "Agents"),
    "online_window_minutes": ("Count as 'online' if active in last N minutes", "number", "5", "Team activity"),
    "idle_session_minutes": ("End a session after N minutes without activity", "number", "30", "Team activity"),
}

_cache: Dict[str, str] = {}
_loaded_at = 0.0


def _default(key):
    d = SCHEMA[key][2]
    return d() if callable(d) else d


def refresh():
    global _cache, _loaded_at
    from app.models.models import AppSetting
    db = SessionLocal()
    try:
        _cache = {r.key: r.value for r in db.query(AppSetting).all()}
    except Exception:
        _cache = {}
    finally:
        db.close()
    _loaded_at = time.time()


def get(key: str) -> str:
    if time.time() - _loaded_at > 60:
        refresh()
    v = _cache.get(key)
    return v if v not in (None, "") else _default(key)


def get_float(key: str) -> float:
    try:
        return float(get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def get_bool(key: str) -> bool:
    return str(get(key)).strip().lower() in ("1", "true", "yes", "on")


def all_values() -> Dict[str, str]:
    return {k: get(k) for k in SCHEMA}
