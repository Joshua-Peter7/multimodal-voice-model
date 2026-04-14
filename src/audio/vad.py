"""
audio/vad.py — Voice Activity Detection using webrtcvad.
Segments incoming audio into speech chunks for STT.
"""

from __future__ import annotations

import asyncio
import struct
import time
from collections import deque
from typing import AsyncGenerator

import webrtcvad

from src.config_loader import cfg
from src.logger import get_logger

log = get_logger(__name__)


class VADProcessor:
    """
    Wraps webrtcvad to detect speech frames and yield complete utterances.
    Frame size must be 10, 20, or 30ms for webrtcvad.
    """

    FRAME_DURATION_MS = 20  # 20ms frames — best balance of latency vs accuracy

    def __init__(self) -> None:
        self._cfg = cfg.audio.vad
        self._sample_rate = cfg.audio.sample_rate
        self._frame_size = int(self._sample_rate * self.FRAME_DURATION_MS / 1000) * 2  # bytes (16-bit)

        self._vad = webrtcvad.Vad(self._cfg.aggressiveness)

        # Ring buffer for context frames
        self._ring_buffer: deque[tuple[bytes, bool]] = deque(
            maxlen=max(1, self._cfg.speech_threshold_ms // self.FRAME_DURATION_MS)
        )
        self._triggered = False
        self._voiced_frames: list[bytes] = []
        self._silence_frames = 0
        self._silence_limit = self._cfg.silence_threshold_ms // self.FRAME_DURATION_MS

    def _is_speech(self, frame: bytes) -> bool:
        try:
            return self._vad.is_speech(frame, self._sample_rate)
        except Exception:
            return False

    def _energy(self, frame: bytes) -> float:
        samples = struct.unpack(f"{len(frame) // 2}h", frame)
        if not samples:
            return 0.0
        return max(abs(s) for s in samples) / 32768.0

    async def process_stream(
        self, audio_stream: AsyncGenerator[bytes, None]
    ) -> AsyncGenerator[bytes, None]:
        """
        Consume raw PCM bytes, yield complete speech utterances.
        Each yielded chunk is a full speech segment ready for STT.
        """
        buffer = b""
        frame_count = 0
        total_bytes = 0

        async for chunk in audio_stream:
            buffer += chunk
            total_bytes += len(chunk)

            while len(buffer) >= self._frame_size:
                frame = buffer[: self._frame_size]
                buffer = buffer[self._frame_size :]
                frame_count += 1
                
                if frame_count == 1:
                    log.info("vad_first_frame", frame_size=self._frame_size)
                elif frame_count % 50 == 0:
                    log.info(
                        "vad_processing",
                        frames_processed=frame_count,
                        total_bytes_received=total_bytes,
                        triggered=self._triggered,
                    )
                
                async for utterance in self._process_frame(frame):
                    log.info(
                        "vad_utterance_yielded",
                        utterance_bytes=len(utterance),
                        total_frames_processed=frame_count,
                    )
                    yield utterance

        # Flush any remaining speech on stream end
        if self._triggered and self._voiced_frames:
            log.info("vad_stream_flushing", voiced_frames=len(self._voiced_frames))
            yield b"".join(self._voiced_frames)
            self._reset()

    async def _process_frame(self, frame: bytes) -> AsyncGenerator[bytes, None]:
        if not self._cfg.enabled:
            yield frame
            return

        # Skip extremely quiet frames (non-speech noise)
        if self._energy(frame) < self._cfg.energy_threshold:
            is_speech = False
        else:
            is_speech = self._is_speech(frame)

        if not self._triggered:
            self._ring_buffer.append((frame, is_speech))
            num_voiced = sum(1 for _, speech in self._ring_buffer if speech)
            # Trigger if majority of ring buffer is speech
            if num_voiced > len(self._ring_buffer) * 0.7:
                self._triggered = True
                log.debug("vad_triggered")
                for f, _ in self._ring_buffer:
                    self._voiced_frames.append(f)
                self._ring_buffer.clear()
        else:
            self._voiced_frames.append(frame)
            self._ring_buffer.append((frame, is_speech))
            num_unvoiced = sum(1 for _, speech in self._ring_buffer if not speech)
            # End utterance after sufficient silence
            if num_unvoiced > len(self._ring_buffer) * 0.9:
                self._silence_frames += 1
                if self._silence_frames >= self._silence_limit:
                    utterance = b"".join(self._voiced_frames)
                    log.debug("vad_utterance_ready", bytes=len(utterance))
                    yield utterance
                    self._reset()
            else:
                self._silence_frames = 0

    def _reset(self) -> None:
        self._triggered = False
        self._voiced_frames = []
        self._ring_buffer.clear()
        self._silence_frames = 0
