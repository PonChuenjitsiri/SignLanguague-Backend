"""
Sentence buffer service — accumulates predicted words and returns
a full sentence after a 5-second idle timeout.

Flow:
  1. ESP32 sends gesture frames → predict → word gets buffered
  2. Timer resets on each new word
  3. After 5s with no new input → sentence is "complete"
  4. Client polls /sentence to retrieve the result
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass


@dataclass
class BufferedWord:
    """A single predicted word in the buffer."""
    word: str
    confidence: float
    titleThai: Optional[str] = None
    titleEng: Optional[str] = None
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()


class SentenceBuffer:
    """
    In-memory sentence buffer with idle-timeout.

    When a new word is added, the idle timer resets.
    After IDLE_TIMEOUT seconds with no new word, the sentence is
    marked as complete and can be retrieved.
    """

    IDLE_TIMEOUT = 5.0  # seconds

    def __init__(self):
        self.words: list[BufferedWord] = []
        self.last_activity: Optional[datetime] = None
        self.completed_sentence: Optional[list[BufferedWord]] = None
        self._timer_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    async def add_word(self, word: BufferedWord) -> dict:
        """
        Add a predicted word to the buffer and reset the idle timer.
        Returns the current buffer state.
        """
        async with self._lock:
            # If there's a completed sentence that hasn't been picked up,
            # clear it and start fresh
            if self.completed_sentence is not None:
                self.completed_sentence = None

            self.words.append(word)
            self.last_activity = datetime.utcnow()

            # Cancel previous timer and start a new one
            if self._timer_task and not self._timer_task.done():
                self._timer_task.cancel()

            self._timer_task = asyncio.create_task(self._idle_timeout())

            return self._get_status()

    async def _idle_timeout(self):
        """Wait for IDLE_TIMEOUT then mark sentence as complete."""
        try:
            await asyncio.sleep(self.IDLE_TIMEOUT)
            async with self._lock:
                if self.words:
                    self.completed_sentence = self.words.copy()
                    self.words = []
                    self.last_activity = None
                    print(f"📝 Sentence complete: {self._sentence_text(self.completed_sentence)}")
        except asyncio.CancelledError:
            pass  # Timer was reset by a new word

    def _sentence_text(self, words: list[BufferedWord]) -> str:
        """Build sentence string from buffered words."""
        return " ".join(
            w.titleThai if w.titleThai else w.word for w in words
        )

    def _get_status(self) -> dict:
        """Get current buffer status."""
        return {
            "buffering": True,
            "word_count": len(self.words),
            "current_words": [
                {"word": w.word, "titleThai": w.titleThai, "confidence": w.confidence}
                for w in self.words
            ],
            "seconds_until_complete": self.IDLE_TIMEOUT,
        }

    async def get_sentence(self) -> Optional[dict]:
        """
        Returns the completed sentence if available.
        Returns None if still buffering.
        """
        async with self._lock:
            if self.completed_sentence:
                result = {
                    "complete": True,
                    "sentence": self._sentence_text(self.completed_sentence),
                    "words": [
                        {
                            "word": w.word,
                            "titleThai": w.titleThai,
                            "titleEng": w.titleEng,
                            "confidence": w.confidence,
                        }
                        for w in self.completed_sentence
                    ],
                    "word_count": len(self.completed_sentence),
                }
                # Clear after retrieval
                self.completed_sentence = None
                return result

            if self.words:
                return {
                    "complete": False,
                    "sentence": self._sentence_text(self.words),
                    "words": [
                        {
                            "word": w.word,
                            "titleThai": w.titleThai,
                            "titleEng": w.titleEng,
                            "confidence": w.confidence,
                        }
                        for w in self.words
                    ],
                    "word_count": len(self.words),
                }

            return None

    async def clear(self):
        """Clear the buffer manually."""
        async with self._lock:
            if self._timer_task and not self._timer_task.done():
                self._timer_task.cancel()
            self.words = []
            self.completed_sentence = None
            self.last_activity = None


# Global singleton instance
sentence_buffer = SentenceBuffer()
