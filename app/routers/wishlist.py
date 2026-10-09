from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import WishlistItem, Listing, User, UserRole
from app.schemas.schemas import WishlistOut
from app.core.security import get_current_user, require_roles

router = APIRouter(prefix="/api/wishlist", tags=["Wishlist"])


@router.get(
    "",
    response_model=List[WishlistOut],
    summary="My saved listings (Customer only)",
    dependencies=[Depends(require_roles(UserRole.CUSTOMER))],
)
def get_wishlist(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return (
        db.query(WishlistItem)
        .filter(WishlistItem.customer_id == current_user.id)
        .order_by(WishlistItem.created_at.desc())
        .all()
    )


@router.post(
    "/{listing_id}",
    response_model=WishlistOut,
    status_code=201,
    summary="Save a listing to my wishlist (Customer only)",
    dependencies=[Depends(require_roles(UserRole.CUSTOMER))],
)
def add_to_wishlist(listing_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found.")

    existing = (
        db.query(WishlistItem)
        .filter(WishlistItem.customer_id == current_user.id, WishlistItem.listing_id == listing_id)
        .first()
    )
    if existing:
        return existing

    item = WishlistItem(customer_id=current_user.id, listing_id=listing_id)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.delete(
    "/{listing_id}",
    status_code=204,
    summary="Remove a listing from my wishlist (Customer only)",
    dependencies=[Depends(require_roles(UserRole.CUSTOMER))],
)
def remove_from_wishlist(listing_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = (
        db.query(WishlistItem)
        .filter(WishlistItem.customer_id == current_user.id, WishlistItem.listing_id == listing_id)
        .first()
    )
    if item:
        db.delete(item)
        db.commit()
    return None
