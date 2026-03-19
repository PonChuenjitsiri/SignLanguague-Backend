import asyncio
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from typing import Optional, Dict, Literal
from enum import Enum

from app.config import get_settings
from app.services.sentence_buffer import sentence_buffer

router = APIRouter(prefix="/api/glove", tags=["Glove Status"])

# ======================================================
# In-memory stores
# ======================================================
_heartbeats: Dict[str, datetime] = {}
_gesture_state: Dict[str, bool] = {}  # { device_id: gesture_active }
_calibrated_hands: Dict[str, Dict[str, bool]] = {}  # { device_id: {"left": False, "right": False} }


class CalibrationStep(str, Enum):
    OPEN = "open"
    CLOSE = "close"
    DONE = "done"


_calibration_state: Dict[str, dict] = {}

TOTAL_ROUNDS = 5

ACTION_TEXT = {
    "open": {"th": "แบมือ แล้วกดปุ่ม", "en": "Open your hand, then press the button"},
    "close": {"th": "กำมือ แล้วกดปุ่ม", "en": "Close your hand, then press the button"},
    "done": {"th": "Calibration เสร็จสิ้น!", "en": "Calibration complete!"},
}


# ======================================================
# Schemas — Heartbeat
# ======================================================
class HeartbeatRequest(BaseModel):
    device_id: str = Field(default="default", description="Unique ID of the glove device")


class HeartbeatResponse(BaseModel):
    status: str = "ok"
    device_id: str
    timestamp: datetime


class GloveStatusResponse(BaseModel):
    device_id: str
    online: bool
    last_heartbeat: Optional[datetime] = None
    timeout_seconds: int


# ======================================================
# Schemas — Calibration
# ======================================================
class CalibrateStartRequest(BaseModel):
    device_id: str = Field(default="default")
    hand: Literal["left", "right"] = Field(default="right", description="Which hand to calibrate")


class CalibrateUpdateRequest(BaseModel):
    device_id: str = Field(default="default")
    step: CalibrationStep = Field(..., description="Current step: open, close, or done")
    round: int = Field(default=1, ge=1, le=5, description="Current round (1-5)")
    hand: Optional[Literal["left", "right"]] = Field(default=None, description="Which hand (optional, keeps current)")


class CalibrateStatusResponse(BaseModel):
    device_id: str
    calibrating: bool
    round: int
    total_rounds: int = TOTAL_ROUNDS
    step: str
    hand: str = "right"
    action_text: str = Field(description="Thai instruction for the user")
    action_text_eng: str = Field(description="English instruction for the user")
    started_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ======================================================
# Schemas — Gesture
# ======================================================
class GestureRequest(BaseModel):
    device_id: str = Field(default="default")


# ══════════════════════════════════════════════════════
#  1. HEARTBEAT — ESP32 health check
# ══════════════════════════════════════════════════════
@router.post("/heartbeat", response_model=HeartbeatResponse)
async def heartbeat(request: HeartbeatRequest = HeartbeatRequest()):
    """
    Receive heartbeat from ESP32 glove.

    ESP32 should call this every 5-10 seconds to report it's alive.
    If no heartbeat is received within the timeout period, the glove
    is considered offline.
    """
    now = datetime.now(timezone.utc)
    _heartbeats[request.device_id] = now
    sentence_buffer._notify_change()  # trigger WS update

    return HeartbeatResponse(
        status="ok",
        device_id=request.device_id,
        timestamp=now,
    )


@router.get("/status", response_model=GloveStatusResponse)
async def get_status(device_id: str = "default"):
    """Check if a glove is online (REST fallback)."""
    return _build_status(device_id)


@router.get("/status/all")
async def get_all_status():
    """Get status of all known glove devices."""
    settings = get_settings()
    timeout = settings.GLOVE_HEARTBEAT_TIMEOUT
    now = datetime.now(timezone.utc)

    devices = []
    for device_id, last_hb in _heartbeats.items():
        elapsed = (now - last_hb).total_seconds()
        devices.append(
            GloveStatusResponse(
                device_id=device_id,
                online=elapsed <= timeout,
                last_heartbeat=last_hb,
                timeout_seconds=timeout,
            )
        )

    return {"devices": devices, "total": len(devices)}


def _build_status(device_id: str) -> GloveStatusResponse:
    settings = get_settings()
    timeout = settings.GLOVE_HEARTBEAT_TIMEOUT
    last_hb = _heartbeats.get(device_id)

    if last_hb is None:
        return GloveStatusResponse(
            device_id=device_id, online=False, timeout_seconds=timeout,
        )

    elapsed = (datetime.now(timezone.utc) - last_hb).total_seconds()
    return GloveStatusResponse(
        device_id=device_id,
        online=elapsed <= timeout,
        last_heartbeat=last_hb,
        timeout_seconds=timeout,
    )


# ══════════════════════════════════════════════════════
#  2. CALIBRATION — ESP32 calibrate flow
# ══════════════════════════════════════════════════════
@router.post("/calibrate/start", response_model=CalibrateStatusResponse)
async def calibrate_start(request: CalibrateStartRequest = CalibrateStartRequest()):
    """
    Start calibration session.

    ESP32 calls this when entering calibration mode (long press > 3s).
    Specify `hand: "left"` or `"right"` to indicate which hand is calibrating.
    """
    now = datetime.now(timezone.utc)
    _calibration_state[request.device_id] = {
        "calibrating": True,
        "round": 1,
        "step": "open",
        "hand": request.hand,
        "started_at": now,
        "updated_at": now,
    }
    sentence_buffer._notify_change()  # trigger WS update

    return _build_calibrate_response(request.device_id)


@router.post("/calibrate/update", response_model=CalibrateStatusResponse)
async def calibrate_update(request: CalibrateUpdateRequest):
    """
    Update calibration progress.

    ESP32 calls this after each button press during calibration:
    - `step: "open"` + `round: N` → waiting for user to open hand
    - `step: "close"` + `round: N` → waiting for user to close hand
    - `step: "done"` → calibration finished
    """
    state = _calibration_state.get(request.device_id)
    if state is None or not state["calibrating"]:
        raise HTTPException(
            status_code=400,
            detail=f"No active calibration for device '{request.device_id}'. Call /calibrate/start first.",
        )

    now = datetime.now(timezone.utc)

    if request.step == CalibrationStep.DONE:
        state["calibrating"] = False
        state["step"] = "done"
        state["updated_at"] = now
        
        if request.device_id not in _calibrated_hands:
            _calibrated_hands[request.device_id] = {"left": False, "right": False}
        hand = state.get("hand", "right")
        _calibrated_hands[request.device_id][hand] = True
    else:
        state["round"] = request.round
        state["step"] = request.step.value
        state["updated_at"] = now

    if request.hand is not None:
        state["hand"] = request.hand

    sentence_buffer._notify_change()  # trigger WS update

    return _build_calibrate_response(request.device_id)


@router.get("/calibrate/status", response_model=CalibrateStatusResponse)
async def calibrate_status(device_id: str = "default"):
    """Get current calibration status & instruction (REST fallback)."""
    return _build_calibrate_response(device_id)


def _build_calibrate_response(device_id: str) -> CalibrateStatusResponse:
    state = _calibration_state.get(device_id)

    if state is None:
        return CalibrateStatusResponse(
            device_id=device_id,
            calibrating=False,
            round=0,
            step="idle",
            hand="right",
            action_text="ยังไม่ได้เริ่ม Calibration",
            action_text_eng="Calibration not started",
        )

    step = state["step"]
    texts = ACTION_TEXT.get(step, {"th": "", "en": ""})

    return CalibrateStatusResponse(
        device_id=device_id,
        calibrating=state["calibrating"],
        round=state["round"],
        step=step,
        hand=state.get("hand", "right"),
        action_text=texts["th"],
        action_text_eng=texts["en"],
        started_at=state.get("started_at"),
        updated_at=state.get("updated_at"),
    )


# ══════════════════════════════════════════════════════
#  3. GESTURE — Start / Stop gesture recording
# ══════════════════════════════════════════════════════
@router.post("/gesture/start")
async def gesture_start(request: GestureRequest = GestureRequest()):
    """
    Start gesture recording session.

    ESP32 calls this when the user presses the button to start making
    a sign language gesture. Activates sentence buffer.
    """
    _gesture_state[request.device_id] = True
    await sentence_buffer.start_recording()

    return {
        "message": "Gesture recording started",
        "gesture_active": True,
        "device_id": request.device_id,
    }


@router.post("/gesture/stop")
async def gesture_stop(request: GestureRequest = GestureRequest()):
    """
    Stop gesture recording and finalize sentence.

    ESP32 calls this when no data for 5s (timeout) or button press.
    """
    _gesture_state[request.device_id] = False
    result = await sentence_buffer.stop_recording()

    return {
        "message": "Gesture recording stopped — sentence finalized",
        "gesture_active": False,
        "device_id": request.device_id,
        "sentence": result,
    }


@router.get("/gesture/status")
async def gesture_status(device_id: str = "default"):
    """Check if gesture recording is currently active."""
    return {
        "device_id": device_id,
        "gesture_active": _gesture_state.get(device_id, False),
        "recording": sentence_buffer.is_recording,
    }


# ══════════════════════════════════════════════════════
#  4. UNIFIED WEBSOCKET — All state in one connection
# ══════════════════════════════════════════════════════
@router.websocket("/ws")
async def ws_unified(websocket: WebSocket, device_id: str = "default"):
    """
    **Single WebSocket** that streams ALL glove state to Frontend.

    Connect: `ws://host/api/glove/ws?device_id=default`

    Pushes JSON on every state change (heartbeat, calibration, gesture, sentence):
    ```json
    {
      "status": "online",
      "state": "gesture",
      "hand": "right",
      "round": "done",
      "thai_word": "ฉันหิว",
      "eng_word": "I hungry",
      "recording": true,
      "complete": false,
      "word_count": 2
    }
    ```

    Field details:
    - `status`: `"online"` / `"offline"` — based on heartbeat timeout
    - `state`: `"idle"` / `"calibrate"` / `"gesture"` — current activity
    - `hand`: `"left"` / `"right"` — which hand is being calibrated
    - `round`: `"1"`-`"5"` / `"done"` — calibration round (or `"done"`)
    - `thai_word`: accumulated Thai sentence (no spaces)
    - `eng_word`: accumulated English sentence (from titleEng)
    - `recording`: true if gesture is being recorded
    - `complete`: true if sentence is finalized
    - `word_count`: number of predicted words
    """
    await websocket.accept()
    settings = get_settings()
    timeout = settings.GLOVE_HEARTBEAT_TIMEOUT

    try:
        while True:
            # Wait for any state change (or timeout for periodic push)
            await sentence_buffer.wait_for_change(timeout=3.0)

            # --- Status ---
            last_hb = _heartbeats.get(device_id)
            online = False
            if last_hb is not None:
                elapsed = (datetime.now(timezone.utc) - last_hb).total_seconds()
                online = elapsed <= timeout

                # Clear device data if offline for more than 3 hours (10800 seconds)
                if elapsed > 10800:
                    _heartbeats.pop(device_id, None)
                    _gesture_state.pop(device_id, None)
                    _calibration_state.pop(device_id, None)
                    _calibrated_hands.pop(device_id, None)
                    await sentence_buffer.clear()
                    online = False
                    last_hb = None

            # --- State ---
            cal_state = _calibration_state.get(device_id)
            calibrating = cal_state["calibrating"] if cal_state else False
            gesture_active = _gesture_state.get(device_id, False)

            if calibrating:
                state = "calibrate"
            elif gesture_active or sentence_buffer.is_recording:
                state = "gesture"
            else:
                state = "idle"

            # --- Calibration details ---
            hand = cal_state.get("hand", "right") if cal_state else "right"
            cal_round = str(cal_state.get("round", 0)) if cal_state else "0"
            cal_step = cal_state.get("step", "idle") if cal_state else "idle"
            if cal_step == "done":
                cal_round = "done"

            # --- Sentence ---
            ws_sentence = await sentence_buffer.get_ws_sentence()

            # --- Calibration flags ---
            cal_hands = _calibrated_hands.get(device_id, {"left": False, "right": False})

            await websocket.send_json({
                "status": "online" if online else "offline",
                "state": state,
                "hand": hand,
                "round": cal_round,
                "thai_word": ws_sentence["thai_word"],
                "eng_word": ws_sentence["eng_word"],
                "recording": ws_sentence["recording"],
                "complete": ws_sentence["complete"],
                "word_count": ws_sentence["word_count"],
                "calibrate_left": cal_hands.get("left", False),
                "calibrate_right": cal_hands.get("right", False),
            })
    except WebSocketDisconnect:
        pass
