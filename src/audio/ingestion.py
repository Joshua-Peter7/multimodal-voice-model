"""
audio/ingestion.py — Captures live microphone audio or accepts streaming input.
Applies noise suppression and feeds chunks to the VAD/STT pipeline.
"""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator, Optional

import numpy as np

from src.config_loader import cfg
from src.logger import get_logger

log = get_logger(__name__)


class NoiseSuppressor:
    """
    Lightweight spectral subtraction noise suppressor.
    For production, consider noisereduce or RNNoise via FFI.
    """

    def __init__(self) -> None:
        self._cfg = cfg.audio.noise_suppression
        self._noise_profile: Optional[np.ndarray] = None
        self._calibration_frames = 0
        self._calibration_target = 10  # frames for noise profile

    def _to_float(self, pcm_bytes: bytes) -> np.ndarray:
        samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
        return samples / 32768.0

    def _to_bytes(self, samples: np.ndarray) -> bytes:
        clipped = np.clip(samples * 32768.0, -32768, 32767)
        return clipped.astype(np.int16).tobytes()

    def process(self, pcm_bytes: bytes) -> bytes:
        if not self._cfg.enabled:
            return pcm_bytes

        samples = self._to_float(pcm_bytes)

        # Build initial noise profile from first ~200ms of audio (assumed noise)
        if self._calibration_frames < self._calibration_target:
            if self._noise_profile is None:
                self._noise_profile = np.abs(samples)
            else:
                self._noise_profile = (
                    0.8 * self._noise_profile + 0.2 * np.abs(samples)
                )
            self._calibration_frames += 1
            return pcm_bytes

        # Spectral subtraction
        magnitude = np.abs(samples)
        noise_est = self._noise_profile * self._cfg.intensity
        denoised = np.sign(samples) * np.maximum(magnitude - noise_est, 0)

        # Update noise profile slowly (adaptive)
        self._noise_profile = 0.95 * self._noise_profile + 0.05 * np.minimum(
            magnitude, self._noise_profile
        )

        return self._to_bytes(denoised)


class AudioIngestion:
    """
    Accepts raw PCM audio bytes (e.g., from a WebSocket) and emits
    preprocessed chunks ready for VAD + STT.
    """

    def __init__(self) -> None:
        self._cfg = cfg.audio
        self._suppressor = NoiseSuppressor()
        self._chunk_bytes = int(
            self._cfg.sample_rate
            * (self._cfg.chunk_duration_ms / 1000)
            * 2  # 16-bit = 2 bytes/sample
        )
        self._buffer = b""

    def ingest(self, raw_bytes: bytes) -> list[bytes]:
        """
        Feed raw PCM bytes; returns list of fixed-size processed chunks.
        Call this for each WebSocket frame received from the speaker.
        """
        self._buffer += raw_bytes
        chunks = []

        while len(self._buffer) >= self._chunk_bytes:
            chunk = self._buffer[: self._chunk_bytes]
            self._buffer = self._buffer[self._chunk_bytes :]
            chunk = self._suppressor.process(chunk)
            chunks.append(chunk)

        return chunks

    async def stream_microphone(self) -> AsyncGenerator[bytes, None]:
        """
        Local microphone capture (for testing / local deployment).
        Yields raw PCM chunks from the default input device.
        """
        try:
            import pyaudio  # Optional — only needed for local mic capture
        except ImportError:
            raise RuntimeError(
                "pyaudio is required for local mic capture: pip install pyaudio"
            )

        pa = pyaudio.PyAudio()
        frames_per_buffer = int(
            self._cfg.sample_rate * self._cfg.chunk_duration_ms / 1000
        )

        stream = pa.open(
            format=pyaudio.paInt16,
            channels=self._cfg.channels,
            rate=self._cfg.sample_rate,
            input=True,
            frames_per_buffer=frames_per_buffer,
        )
        log.info("microphone_open", rate=self._cfg.sample_rate)

        loop = asyncio.get_event_loop()
        try:
            while True:
                raw = await loop.run_in_executor(
                    None, stream.read, frames_per_buffer, False
                )
                processed = self._suppressor.process(raw)
                yield processed
        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()
            log.info("microphone_closed")
