from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Listing, ListingType, User, UserRole
from app.schemas.schemas import ListingCreate, ListingOut
from app.core.security import get_current_user, require_roles

router = APIRouter(prefix="/api/listings", tags=["Listings (Hotels / Flights / Packages)"])


@router.get(
    "",
    response_model=List[ListingOut],
    summary="Browse hotels, flights and packages",
    description="Public endpoint. Filter by `type` (hotel / flight / package) and/or `location`.",
)
def list_listings(
    type: Optional[ListingType] = Query(None),
    location: Optional[str] = Query(None),
    limit: Optional[int] = Query(None, ge=1, le=100, description="Cap the number of results, most recent first"),
    db: Session = Depends(get_db),
):
    query = db.query(Listing).filter(Listing.is_active == True)  # noqa: E712
    if type:
        query = query.filter(Listing.type == type)
    if location:
        query = query.filter(Listing.location.ilike(f"%{location}%"))
    query = query.order_by(Listing.created_at.desc())
    if limit:
        query = query.limit(limit)
    return query.all()


@router.get("/{listing_id}", response_model=ListingOut, summary="Get a single listing")
def get_listing(listing_id: int, db: Session = Depends(get_db)):
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found.")
    return listing


@router.post(
    "",
    response_model=ListingOut,
    status_code=201,
    summary="Create a listing (Agent / Distributor only)",
    dependencies=[Depends(require_roles(UserRole.AGENT, UserRole.DISTRIBUTOR))],
)
def create_listing(
    payload: ListingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    listing = Listing(**payload.model_dump(), owner_id=current_user.id)
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return listing


@router.put(
    "/{listing_id}",
    response_model=ListingOut,
    summary="Update a listing you own (Agent / Distributor only)",
    dependencies=[Depends(require_roles(UserRole.AGENT, UserRole.DISTRIBUTOR))],
)
def update_listing(
    listing_id: int,
    payload: ListingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found.")
    if listing.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only edit listings you created.")

    for field, value in payload.model_dump().items():
        setattr(listing, field, value)
    db.commit()
    db.refresh(listing)
    return listing


@router.delete(
    "/{listing_id}",
    status_code=204,
    summary="Deactivate a listing you own (Agent / Distributor only)",
    dependencies=[Depends(require_roles(UserRole.AGENT, UserRole.DISTRIBUTOR))],
)
def delete_listing(
    listing_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found.")
    if listing.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only remove listings you created.")
    listing.is_active = False
    db.commit()
    return None
