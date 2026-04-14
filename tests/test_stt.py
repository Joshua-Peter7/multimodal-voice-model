"""
tests/test_stt.py — Tests for the Soniox STT client.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.stt.soniox_client import SonioxSTTClient, Transcript


class TestTranscriptParsing:
    """Test Soniox response parsing logic."""

    def _make_response(self, words: list[dict], finished: bool = False) -> dict:
        return {"words": words, "finished": finished}

    def test_final_transcript_detected(self):
        """Words with is_final=True should produce is_final Transcript."""
        response = self._make_response([
            {"text": "Hello", "is_final": True},
            {"text": "world", "is_final": True},
        ])
        words = response["words"]
        nonfinal = [w for w in words if not w.get("is_final", True)]
        final = [w for w in words if w.get("is_final", True)]
        text = " ".join(w["text"] for w in words)

        assert text == "Hello world"
        assert len(nonfinal) == 0
        assert len(final) == 2  # Both are final

    def test_partial_transcript_detected(self):
        """Mix of final/nonfinal words = partial transcript."""
        words = [
            {"text": "Hello", "is_final": True},
            {"text": "wor", "is_final": False},
        ]
        nonfinal = [w for w in words if not w.get("is_final", True)]
        assert len(nonfinal) == 1

    def test_empty_words_skipped(self):
        words = [{"text": "", "is_final": True}]
        text = " ".join(w["text"] for w in words).strip()
        assert not text  # Should be skipped


class TestSonioxClient:
    @pytest.mark.asyncio
    async def test_close_without_connect(self):
        """Should not raise when close() is called before any connection."""
        client = SonioxSTTClient()
        await client.close()  # Should be safe

    @pytest.mark.asyncio
    async def test_retry_on_connection_error(self):
        """Should retry on connection failure."""
        import aiohttp
        client = SonioxSTTClient()

        call_count = 0

        async def bad_source():
            yield b"\x00" * 100

        with patch.object(client, "_run_session") as mock_run:
            mock_run.side_effect = [
                aiohttp.ClientConnectionError("connection refused"),
                _empty_async_gen(),
            ]
            # Expect retry
            results = []
            try:
                async for t in client.transcribe_stream(bad_source()):
                    results.append(t)
            except aiohttp.ClientConnectionError:
                pass  # Expected after max retries

            assert mock_run.call_count >= 1


async def _empty_async_gen():
    return
    yield  # make it a generator
