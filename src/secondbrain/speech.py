"""Local speech-to-text for Telegram voice notes (faster-whisper on the CPU). The audio never leaves this PC."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import BinaryIO, Protocol

DEFAULT_MODEL = "small"  # multilingual, about 460 MB; "medium" is more accurate but slower and 1.5 GB


class SpeechError(Exception):
    pass


class Transcriber(Protocol):
    def transcribe(self, audio: BinaryIO) -> str: ...


class WhisperTranscriber:
    """Loads the model on first use (a few seconds, about 1 GB RAM) and handles one note at a time."""

    def __init__(self, model: str = DEFAULT_MODEL, language: str | None = None, download_root: Path | None = None,
                 threads: int = 8):
        self.model_name = model
        self.language = language or None  # None = detect; set "en" if Hinglish comes out in the wrong script
        self.download_root = str(download_root) if download_root else None
        self.threads = threads
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8",
                                       cpu_threads=self.threads, download_root=self.download_root)
        return self._model

    def transcribe(self, audio: BinaryIO) -> str:
        with self._lock:
            try:
                segments, _info = self._load().transcribe(audio, language=self.language, vad_filter=True,
                                                          beam_size=5)
                return " ".join(seg.text.strip() for seg in segments).strip()
            except Exception as e:  # corrupt audio, missing model, out of memory: one clear error for the caller
                raise SpeechError(type(e).__name__) from e
