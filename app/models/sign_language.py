from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class SignLanguageModel(BaseModel):
    """MongoDB document model for sign language entries."""

    titleThai: str = Field(..., description="Thai title of the sign")
    titleEng: str = Field(..., description="English title of the sign")
    category: str = Field(..., description="Category (e.g., Basic, Greeting, Number)")
    signMethod: str = Field(..., description="Description of how to perform the sign")
    imageUrl: Optional[str] = Field(default="", description="URL of demonstration image")
    videoUrl: Optional[str] = Field(default="", description="URL of gesture demonstration video")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
