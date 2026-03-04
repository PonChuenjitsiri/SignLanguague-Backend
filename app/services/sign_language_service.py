from bson import ObjectId
from datetime import datetime
from typing import List, Optional

from app.database import get_database


class SignLanguageService:
    """Service layer for sign language CRUD operations."""

    COLLECTION_NAME = "sign_languages"

    @staticmethod
    def _get_collection():
        db = get_database()
        return db[SignLanguageService.COLLECTION_NAME]

    @staticmethod
    async def get_all(category: Optional[str] = None) -> List[dict]:
        """Get all sign language entries, optionally filtered by category."""
        collection = SignLanguageService._get_collection()
        query = {}
        if category:
            query["category"] = category
        cursor = collection.find(query)
        return await cursor.to_list(length=1000)

    @staticmethod
    async def get_by_id(sign_id: str) -> Optional[dict]:
        """Get a sign language entry by ID."""
        collection = SignLanguageService._get_collection()
        return await collection.find_one({"_id": ObjectId(sign_id)})

    @staticmethod
    async def create(sign_data: dict) -> dict:
        """Create a new sign language entry."""
        collection = SignLanguageService._get_collection()
        now = datetime.utcnow()
        sign_data["created_at"] = now
        sign_data["updated_at"] = now
        result = await collection.insert_one(sign_data)
        return await collection.find_one({"_id": result.inserted_id})

    @staticmethod
    async def update(sign_id: str, sign_data: dict) -> Optional[dict]:
        """Update a sign language entry."""
        collection = SignLanguageService._get_collection()
        # Remove None values so only provided fields are updated
        update_data = {k: v for k, v in sign_data.items() if v is not None}
        if not update_data:
            return await SignLanguageService.get_by_id(sign_id)
        update_data["updated_at"] = datetime.utcnow()
        await collection.update_one(
            {"_id": ObjectId(sign_id)},
            {"$set": update_data},
        )
        return await collection.find_one({"_id": ObjectId(sign_id)})

    @staticmethod
    async def delete(sign_id: str) -> bool:
        """Delete a sign language entry."""
        collection = SignLanguageService._get_collection()
        result = await collection.delete_one({"_id": ObjectId(sign_id)})
        return result.deleted_count > 0

    @staticmethod
    async def find_by_title_eng(title_eng: str) -> Optional[dict]:
        """Find a sign language entry by English title."""
        collection = SignLanguageService._get_collection()
        return await collection.find_one(
            {"titleEng": {"$regex": f"^{title_eng}$", "$options": "i"}}
        )

    @staticmethod
    async def find_by_label(predicted_label: str) -> Optional[dict]:
        """
        Find a sign language entry by matching the model's predicted label
        against the 'label' field in the database.

        Handles variant labels like:
          - "no_right" or "no_left" → tries "no_right", then "no"
          - "hello" → tries "hello" directly

        Strips directional suffixes (_right, _left) as fallback.
        """
        collection = SignLanguageService._get_collection()

        # 1. Exact match first
        entry = await collection.find_one(
            {"label": {"$regex": f"^{predicted_label}$", "$options": "i"}}
        )
        if entry:
            return entry

        # 2. Strip directional suffixes and try again
        suffixes = ["_right", "_left", "_r", "_l"]
        base_label = predicted_label
        for suffix in suffixes:
            if base_label.endswith(suffix):
                base_label = base_label[: -len(suffix)]
                break

        if base_label != predicted_label:
            entry = await collection.find_one(
                {"label": {"$regex": f"^{base_label}$", "$options": "i"}}
            )
            if entry:
                return entry

        # 3. Fallback: try matching titleEng
        return await SignLanguageService.find_by_title_eng(predicted_label)
