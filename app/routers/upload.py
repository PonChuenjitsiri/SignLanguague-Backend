from fastapi import APIRouter, UploadFile, File, Form, HTTPException

from app.services.minio_service import MinioService
from app.services.sign_language_service import SignLanguageService

router = APIRouter(prefix="/api/sign-languages", tags=["Sign Languages"])

ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp"}
ALLOWED_VIDEO_TYPES = {"video/mp4", "video/quicktime", "video/x-msvideo", "video/webm"}


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
    - `file`: image file (png, jpg, webp, gif)
    """
    # 1. Find the sign language entry by label
    sign_entry = await SignLanguageService.find_by_label(label)
    if not sign_entry:
        raise HTTPException(
            status_code=404,
            detail=f"Sign language entry with label '{label}' not found",
        )

    # 2. Validate file type
    if file.content_type and file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type '{file.content_type}'. Allowed: png, jpg, gif, webp",
        )

    # 3. Read file
    file_data = await file.read()
    if not file_data:
        raise HTTPException(status_code=400, detail="Empty file")

    # 4. Determine file extension and object name
    ext = file.filename.rsplit(".", 1)[-1] if "." in file.filename else "png"
    object_name = f"signs/{label}.{ext}"

    # 5. Upload to MinIO
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

    # 6. Update the sign language entry with the image URL
    sign_id = str(sign_entry["_id"])
    await SignLanguageService.update(sign_id, {"imageUrl": image_url})

    return {
        "message": f"Image uploaded for '{label}'",
        "label": label,
        "imageUrl": image_url,
        "titleThai": sign_entry.get("titleThai"),
    }


@router.post("/uploadvideo")
async def upload_video(
    label: str = Form(..., description="Label of the sign language entry (e.g. 'hello')"),
    file: UploadFile = File(..., description="Video file demonstrating the sign gesture"),
):
    """
    Upload a gesture demonstration video for a sign language entry.

    - Uploads the video to MinIO
    - Updates the sign language entry's `videoUrl` field

    Form data:
    - `label`: label to match (e.g. "hello")
    - `file`: video file (mp4, mov, avi, webm)
    """
    # 1. Find the sign language entry by label
    sign_entry = await SignLanguageService.find_by_label(label)
    if not sign_entry:
        raise HTTPException(
            status_code=404,
            detail=f"Sign language entry with label '{label}' not found",
        )

    # 2. Validate file type
    if file.content_type and file.content_type not in ALLOWED_VIDEO_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type '{file.content_type}'. Allowed: mp4, mov, avi, webm",
        )

    # 3. Read file
    file_data = await file.read()
    if not file_data:
        raise HTTPException(status_code=400, detail="Empty file")

    # 4. Determine file extension and object name
    ext = file.filename.rsplit(".", 1)[-1] if "." in file.filename else "mp4"
    object_name = f"videos/{label}.{ext}"

    # 5. Upload to MinIO
    try:
        video_url = MinioService.upload_file(
            file_data=file_data,
            object_name=object_name,
            content_type=file.content_type or "video/mp4",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload to MinIO: {e}",
        )

    # 6. Update the sign language entry with the video URL
    sign_id = str(sign_entry["_id"])
    await SignLanguageService.update(sign_id, {"videoUrl": video_url})

    return {
        "message": f"Video uploaded for '{label}'",
        "label": label,
        "videoUrl": video_url,
        "titleThai": sign_entry.get("titleThai"),
    }
