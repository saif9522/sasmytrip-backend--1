"""
Which API serves which service — set in .env, e.g.

    TRAIN_PROVIDER=mock        (default for every service)
    BUS_PROVIDER=mybus         (after you add a 'mybus' adapter below)

Service keys: train, bus, cab, cruise, hajj_umrah, travel_insurance,
money_exchange, visa, package, activity
"""
import os

from app.services.providers.base import ServiceProvider
from app.services.providers.mock import MockProvider

SERVICES = {
    "train": "Trains", "bus": "Buses", "cab": "Cabs", "cruise": "Cruise", "hajj_umrah": "Hajj & Umrah",
    "travel_insurance": "Travel Insurance", "money_exchange": "Money Exchange", "visa": "Visa",
    "package": "Holiday Packages", "activity": "Activities",
}

# How many travellers a search is for (used for pricing and traveller forms)
PAX_KEY = {
    "train": "travellers", "bus": "seats", "cruise": "travellers", "hajj_umrah": "travellers",
    "travel_insurance": "travellers", "visa": "travellers", "package": "travellers", "activity": "participants",
}

# Register real adapters here:  PROVIDERS["bus"]["mybus"] = MyBusProvider
PROVIDERS = {svc: {"mock": (lambda s=svc: MockProvider(s))} for svc in SERVICES}

# Example (uncomment after creating the file):
# from app.services.providers.example_http import ExampleHttpProvider
# PROVIDERS["bus"]["example"] = lambda: ExampleHttpProvider("bus")


def provider_name(service: str) -> str:
    return os.getenv(f"{service.upper()}_PROVIDER", "mock").strip().lower() or "mock"


def get_provider(service: str) -> ServiceProvider:
    if service not in SERVICES:
        raise KeyError(service)
    name = provider_name(service)
    factory = PROVIDERS[service].get(name) or PROVIDERS[service]["mock"]
    return factory()


def pax_count(service: str, params: dict) -> int:
    key = PAX_KEY.get(service)
    try:
        return max(1, min(30, int(params.get(key, 1)))) if key else 1
    except (TypeError, ValueError):
        return 1
