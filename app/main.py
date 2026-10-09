import os

from dotenv import load_dotenv

# Load .env before anything reads os.getenv (JWT secret, TBO credentials, CORS).
load_dotenv()

import logging  # noqa: E402
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.routers import auth, listings, bookings, admin, wishlist, reviews, notifications, users  # noqa: E402
from app.routers import travel, offers, enquiries, home_content  # noqa: E402

# Creates tables only if they don't already exist — never drops/recreates
# existing tables, so real data in sasmytrip.db is preserved.
Base.metadata.create_all(bind=engine)

# Create / sync the Super Admin from .env (needs the tables above to exist).
auth.seed_super_admin()
offers.seed_offers()
home_content.seed_home_cards()

app = FastAPI(
    title="SaSmyTrip Travel API",
    description=(
        "REST API powering the SaSmyTrip (sasmytrip.com) travel platform — flights, "
        "hotels, holiday packages and bookings, with five account types: **Customer**, "
        "**Agent**, **Distributor**, **Admin**, and **Super Admin**.\n\n"
        "Interactive Swagger docs are available at `/docs` and ReDoc at `/redoc`."
    ),
    version="1.1.0",
    contact={"name": "SaSmyTrip Engineering", "url": "https://www.sasmytrip.com"},
)

# Default origins cover local dev. Add your real domain(s) via the
# CORS_EXTRA_ORIGINS env var (comma-separated) when deploying — e.g.
# CORS_EXTRA_ORIGINS=https://www.sasmytrip.com,https://sasmytrip.com
DEFAULT_ORIGINS = [
    "http://localhost:5173", "http://127.0.0.1:5173",   # Vite dev server
    "https://www.sasmytrip.com", "https://sasmytrip.com",  # production
]
extra_origins = [o.strip() for o in os.getenv("CORS_EXTRA_ORIGINS", "").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=DEFAULT_ORIGINS + extra_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(listings.router)
app.include_router(bookings.router)
app.include_router(wishlist.router)
app.include_router(reviews.router)
app.include_router(notifications.router)
app.include_router(admin.router)
# Live flights & hotels via TBO API
app.include_router(travel.flights_router)
app.include_router(travel.hotels_router)
app.include_router(travel.bookings_router)
app.include_router(travel.admin_router)
app.include_router(offers.router)
app.include_router(enquiries.router)
app.include_router(home_content.router)


@app.get("/", tags=["Health"], summary="API health check")
def health_check():
    from app.services.tbo.config import settings as tbo
    return {"status": "ok", "service": "SaSmyTrip Travel API", "docs": "/docs", "tbo_mode": tbo.mode}
