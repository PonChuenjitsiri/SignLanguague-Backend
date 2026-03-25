from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List

from app.schemas.device import (
    DeviceCreate,
    DeviceUpdate,
    DeviceResponse,
)
from app.services.device_service import DeviceService

router = APIRouter(prefix="/api/devices", tags=["Devices"])


@router.get("/", response_model=List[DeviceResponse])
async def get_all_devices():
    """Get all registered devices."""
    devices = await DeviceService.get_all()
    return devices


@router.get("/{device_id}", response_model=DeviceResponse)
async def get_device_by_id(device_id: str):
    """Get a device by ID."""
    device = await DeviceService.get_by_id(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return device


@router.post("/", response_model=DeviceResponse, status_code=201)
async def create_device(device_data: DeviceCreate):
    """Register a new device and assign a model."""
    try:
        device = await DeviceService.create(device_data.model_dump())
        return device
    except ValueError as e:
        # ดัก Error กรณีส่งชื่อ model ผิด
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{device_id}", response_model=DeviceResponse)
async def update_device(device_id: str, device_data: DeviceUpdate):
    """Update a device's assigned model."""
    try:
        existing = await DeviceService.get_by_id(device_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Device not found")
            
        updated = await DeviceService.update(device_id, device_data.model_dump())
        return updated
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{device_id}")
async def delete_device(device_id: str):
    """Delete a device."""
    deleted = await DeviceService.delete(device_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Device not found")
    return {"message": "Device deleted successfully"}