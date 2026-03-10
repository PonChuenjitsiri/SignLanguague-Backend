from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from app.utils.object_id import PyObjectId


class SignLanguageCreate(BaseModel):
    """Schema for creating a new sign language entry."""

    titleThai: str = Field(..., json_schema_extra={"example": "สวัสดี"})
    titleEng: str = Field(..., json_schema_extra={"example": "Hello"})
    label: str = Field(..., json_schema_extra={"example": "hello"})
    category: str = Field(..., json_schema_extra={"example": "Basic"})
    signMethod: str = Field(
        ...,
        json_schema_extra={"example": "พนมมือไว้ที่ระดับอก (ท่าไหว้ปกติ)"},
    )
    imageUrl: Optional[str] = Field(
        default="",
        json_schema_extra={"example": "https://example.com/hello.png"},
    )
    videoUrl: Optional[str] = Field(
        default="",
        json_schema_extra={"example": "https://example.com/hello.mp4"},
    )


class SignLanguageUpdate(BaseModel):
    """Schema for updating a sign language entry (all fields optional)."""

    titleThai: Optional[str] = None
    titleEng: Optional[str] = None
    label: Optional[str] = None
    category: Optional[str] = None
    signMethod: Optional[str] = None
    imageUrl: Optional[str] = None
    videoUrl: Optional[str] = None


class SignLanguageResponse(BaseModel):
    """Schema for sign language entry response."""

    id: PyObjectId = Field(alias="_id")
    titleThai: str
    titleEng: str
    label: str
    category: str
    signMethod: str
    imageUrl: Optional[str] = ""
    videoUrl: Optional[str] = ""
    created_at: datetime
    updated_at: datetime

    model_config = {
        "populate_by_name": True,
    }
