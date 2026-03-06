"""
Sentence buffer service — accumulates predicted words between
START_SIGNAL and STOP_SIGNAL from the ESP32 glove.

Flow:
  1. ESP32 POST /signal → {"msg": "START_SIGNAL"}  →  buffer enters "recording" mode
  2. ESP32 POST /predict/raw → predict → word gets buffered (repeat N times)
  3. ESP32 POST /signal → {"msg": "STOP_SIGNAL"}   →  sentence finalized
  4. Client GET /sentence → returns all accumulated words
"""

import asyncio
from datetime import datetime
from typing import Optional
from dataclasses import dataclass


@dataclass
class BufferedWord:
    """A single predicted word in the buffer."""
    word: str
    confidence: float
    titleThai: Optional[str] = None
    titleEng: Optional[str] = None
    label: Optional[str] = None
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()


class SentenceBuffer:
    """
    Signal-based sentence buffer.

    - start_recording() → called when ESP32 sends START_SIGNAL
    - add_word()        → called after each prediction
    - stop_recording()  → called when ESP32 sends STOP_SIGNAL → finalizes sentence
    - get_sentence()    → returns status or completed sentence
    - wait_for_change() → await state change (for WebSocket push)
    """

    def __init__(self):
        self.words: list[BufferedWord] = []
        self.is_recording: bool = False
        self.completed_sentence: Optional[list[BufferedWord]] = None
        self.recording_started_at: Optional[datetime] = None
        self._lock = asyncio.Lock()
        self._change_event = asyncio.Event()

    def _notify_change(self):
        """Signal that state has changed (for WebSocket listeners)."""
        self._change_event.set()
        self._change_event = asyncio.Event()  # reset for next wait

    async def wait_for_change(self, timeout: float = 5.0) -> bool:
        """Wait for a state change. Returns True if changed, False if timeout."""
        try:
            await asyncio.wait_for(self._change_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def start_recording(self):
        """Called when ESP32 sends START_SIGNAL."""
        async with self._lock:
            self.completed_sentence = None
            self.words = []
            self.is_recording = True
            self.recording_started_at = datetime.utcnow()
            self._notify_change()
            print("🎙️ Recording started — waiting for gestures...")

    async def stop_recording(self) -> dict:
        """Called when ESP32 sends STOP_SIGNAL. Finalizes the sentence."""
        async with self._lock:
            self.is_recording = False

            if self.words:
                self.completed_sentence = self.words.copy()
                sentence_text = self._sentence_text(self.completed_sentence)
                print(f"📝 Sentence complete: {sentence_text}")
            else:
                self.completed_sentence = []
                print("📝 Recording stopped — no words captured")

            self.words = []
            self.recording_started_at = None
            self._notify_change()

            return self._completed_result()

    async def add_word(self, word: BufferedWord) -> dict:
        """Add a predicted word to the buffer. Returns current buffer state."""
        async with self._lock:
            self.words.append(word)
            self._notify_change()
            return self._get_status()

    async def get_sentence(self) -> Optional[dict]:
        """
        Returns:
          - Recording in progress → {"complete": false, "recording": true, words so far}
          - Completed sentence    → {"complete": true, words}
          - Empty                 → None
        """
        async with self._lock:
            if self.completed_sentence is not None:
                return self._completed_result()

            if self.is_recording:
                return {
                    "complete": False,
                    "recording": True,
                    "sentence": self._sentence_text(self.words),
                    "words": [self._word_dict(w) for w in self.words],
                    "word_count": len(self.words),
                }

            return None

    async def clear(self):
        """Clear the buffer manually."""
        async with self._lock:
            self.words = []
            self.completed_sentence = None
            self.is_recording = False
            self.recording_started_at = None
            self._notify_change()

    # --------------------------------------------------
    # Sentence builders
    # --------------------------------------------------
    def _sentence_text(self, words: list[BufferedWord]) -> str:
        """Build sentence string (spaced) — prefer titleThai, fallback to word."""
        return " ".join(
            w.titleThai if w.titleThai else w.word for w in words
        )

    def _thai_sentence(self, words: list[BufferedWord]) -> str:
        """Build Thai sentence (no spaces — natural Thai writing)."""
        return "".join(
            w.titleThai if w.titleThai else w.word for w in words
        )

    def _eng_sentence(self, words: list[BufferedWord]) -> str:
        """Build English sentence from titleEng of each word."""
        parts = [w.titleEng for w in words if w.titleEng]
        return " ".join(parts)

    # --------------------------------------------------
    # WebSocket format: { thai_word, eng_word, ... }
    # --------------------------------------------------
    async def get_ws_sentence(self) -> dict:
        """Get sentence in WebSocket format for Frontend."""
        async with self._lock:
            if self.completed_sentence is not None:
                words = self.completed_sentence
                return {
                    "thai_word": self._thai_sentence(words),
                    "eng_word": self._eng_sentence(words),
                    "recording": False,
                    "complete": True,
                    "word_count": len(words),
                }

            if self.is_recording:
                return {
                    "thai_word": self._thai_sentence(self.words),
                    "eng_word": self._eng_sentence(self.words),
                    "recording": True,
                    "complete": False,
                    "word_count": len(self.words),
                }

            return {
                "thai_word": "",
                "eng_word": "",
                "recording": False,
                "complete": False,
                "word_count": 0,
            }

    def _word_dict(self, w: BufferedWord) -> dict:
        return {
            "word": w.word,
            "titleThai": w.titleThai,
            "titleEng": w.titleEng,
            "label": w.label,
            "confidence": w.confidence,
        }

    def _get_status(self) -> dict:
        return {
            "recording": self.is_recording,
            "word_count": len(self.words),
            "current_words": [self._word_dict(w) for w in self.words],
        }

    def _completed_result(self) -> dict:
        words = self.completed_sentence or []
        return {
            "complete": True,
            "recording": False,
            "sentence": self._sentence_text(words),
            "words": [self._word_dict(w) for w in words],
            "word_count": len(words),
        }


# Global singleton
sentence_buffer = SentenceBuffer()
