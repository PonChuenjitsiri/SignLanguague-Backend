from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.services.data_collector import collector_instance

router = APIRouter(
    prefix="/collector",
    tags=["Data Collector"],
)

class StartRequest(BaseModel):
    name: str
    gesture: str

@router.post("/start")
async def start_collection(req: StartRequest):
    """Start reading from the serial port to collect gesture data."""
    success, msg = collector_instance.start(req.name, req.gesture)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg, "status": collector_instance.get_status()}

@router.post("/stop")
async def stop_collection():
    """Stop the data collection process."""
    success, msg = collector_instance.stop()
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg, "status": collector_instance.get_status()}

@router.get("/status")
async def get_status():
    """Get the current status of the data collector."""
    return collector_instance.get_status()
