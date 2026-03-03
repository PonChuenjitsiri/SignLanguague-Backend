from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List

from app.schemas.sign_language import (
    SignLanguageCreate,
    SignLanguageUpdate,
    SignLanguageResponse,
)
from app.services.sign_language_service import SignLanguageService

router = APIRouter(prefix="/api/sign-languages", tags=["Sign Languages"])


@router.get("/", response_model=List[SignLanguageResponse])
async def get_all_signs(category: Optional[str] = Query(None, description="Filter by category")):
    """Get all sign language entries. Optionally filter by category."""
    signs = await SignLanguageService.get_all(category=category)
    return signs


@router.get("/{sign_id}", response_model=SignLanguageResponse)
async def get_sign_by_id(sign_id: str):
    """Get a sign language entry by ID."""
    sign = await SignLanguageService.get_by_id(sign_id)
    if not sign:
        raise HTTPException(status_code=404, detail="Sign language entry not found")
    return sign


@router.post("/", response_model=SignLanguageResponse, status_code=201)
async def create_sign(sign_data: SignLanguageCreate):
    """Create a new sign language entry."""
    sign = await SignLanguageService.create(sign_data.model_dump())
    return sign


@router.put("/{sign_id}", response_model=SignLanguageResponse)
async def update_sign(sign_id: str, sign_data: SignLanguageUpdate):
    """Update a sign language entry."""
    existing = await SignLanguageService.get_by_id(sign_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Sign language entry not found")
    updated = await SignLanguageService.update(sign_id, sign_data.model_dump())
    return updated


@router.delete("/{sign_id}")
async def delete_sign(sign_id: str):
    """Delete a sign language entry."""
    deleted = await SignLanguageService.delete(sign_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Sign language entry not found")
    return {"message": "Sign language entry deleted successfully"}
