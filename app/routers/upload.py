from fastapi import APIRouter, UploadFile, File, Form, HTTPException

from app.services.minio_service import MinioService
from app.services.sign_language_service import SignLanguageService

router = APIRouter(prefix="/api/sign-languages", tags=["Sign Languages"])


@router.post("/uploadpicture")
async def upload_picture(
    label: str = Form(..., description="Label of the sign language entry (e.g. 'hello')"),
    file: UploadFile = File(..., description="Image file for the sign"),
):
    """
    Upload an image for a sign language entry.

    - Uploads the file to MinIO
    - Updates the sign language entry's `imageUrl` field

    Form data:
    - `label`: label to match (e.g. "hello")
    - `file`: image file (png, jpg, etc.)
    """
    # 1. Find the sign language entry by label
    sign_entry = await SignLanguageService.find_by_label(label)
    if not sign_entry:
        raise HTTPException(
            status_code=404,
            detail=f"Sign language entry with label '{label}' not found",
        )

    # 2. Read file
    file_data = await file.read()
    if not file_data:
        raise HTTPException(status_code=400, detail="Empty file")

    # 3. Determine file extension and object name
    ext = file.filename.rsplit(".", 1)[-1] if "." in file.filename else "png"
    object_name = f"signs/{label}.{ext}"

    # 4. Upload to MinIO
    try:
        image_url = MinioService.upload_file(
            file_data=file_data,
            object_name=object_name,
            content_type=file.content_type or "image/png",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload to MinIO: {e}",
        )

    # 5. Update the sign language entry with the image URL
    sign_id = str(sign_entry["_id"])
    await SignLanguageService.update(sign_id, {"imageUrl": image_url})

    return {
        "message": f"Image uploaded for '{label}'",
        "label": label,
        "imageUrl": image_url,
        "titleThai": sign_entry.get("titleThai"),
    }
