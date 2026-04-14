"""
tests/test_pipeline.py — Unit and integration tests for pipeline components.
Run: pytest tests/ -v
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.moderation.content_moderator import ContentModerator
from src.translation.llm_translator import _parse_json_from_response, _build_llama_prompt
from src.audio.ingestion import NoiseSuppressor, AudioIngestion
from src.config_loader import cfg


# ── Moderation Tests ─────────────────────────────────────────

class TestContentModerator:
    def setup_method(self):
        self.mod = ContentModerator()

    def test_clean_text_passes(self):
        result = self.mod.screen("Hello, how are you today?")
        assert result.flagged is False
        assert result.text == "Hello, how are you today?"

    def test_empty_text(self):
        result = self.mod.screen("")
        assert result.flagged is False

    def test_screen_translations_passthrough(self):
        translations = {"hi": "नमस्ते", "te": "హలో", "ta": "வணக்கம்"}
        cleaned, flagged = self.mod.screen_translations(translations)
        assert cleaned == translations
        assert flagged is False


# ── Translation JSON Parser Tests ─────────────────────────────

class TestJsonParser:
    def test_clean_json(self):
        raw = '{"hi": "नमस्ते", "te": "హలో"}'
        result = _parse_json_from_response(raw)
        assert result == {"hi": "नमस्ते", "te": "హలో"}

    def test_json_with_primed_brace(self):
        # We prime with { so model output doesn't include it
        raw = '"hi": "नमस्ते", "te": "హలో"}'
        result = _parse_json_from_response(raw)
        assert result is not None
        assert "hi" in result

    def test_json_in_markdown_fence(self):
        raw = '```json\n{"hi": "नमस्ते"}\n```'
        result = _parse_json_from_response(raw)
        assert result == {"hi": "नमस्ते"}

    def test_garbage_returns_none(self):
        result = _parse_json_from_response("This is not JSON at all.")
        assert result is None

    def test_prompt_builder(self):
        from src.config_loader import LanguageConfig
        langs = [
            LanguageConfig("hi", "Hindi", "v1", 0.5, 0.75, True),
            LanguageConfig("te", "Telugu", "v2", 0.5, 0.75, True),
        ]
        prompt = _build_llama_prompt("Hello world", langs)
        assert "Hello world" in prompt
        assert "Hindi" in prompt
        assert "Telugu" in prompt
        assert "<|begin_of_text|>" in prompt


# ── Audio Tests ───────────────────────────────────────────────

class TestNoiseSuppressor:
    def test_passthrough_when_disabled(self):
        import struct
        # Override config for test
        suppressor = NoiseSuppressor()
        suppressor._cfg = MagicMock()
        suppressor._cfg.enabled = False

        raw = struct.pack("1024h", *([100] * 1024))
        result = suppressor.process(raw)
        assert result == raw

    def test_processes_pcm_bytes(self):
        import struct
        suppressor = NoiseSuppressor()
        raw = struct.pack("512h", *([1000] * 512))
        # Should not raise
        result = suppressor.process(raw)
        assert isinstance(result, bytes)
        assert len(result) == len(raw)


class TestAudioIngestion:
    def test_chunk_splitting(self):
        ingestion = AudioIngestion()
        # Feed 2x the chunk size → expect 2 chunks back
        chunk_bytes = ingestion._chunk_bytes
        big_input = b"\x00\x01" * (chunk_bytes)  # 1 full chunk
        chunks = ingestion.ingest(big_input)
        assert len(chunks) == 1
        assert len(chunks[0]) == chunk_bytes

    def test_partial_chunk_buffered(self):
        ingestion = AudioIngestion()
        small_input = b"\x00" * 10
        chunks = ingestion.ingest(small_input)
        assert chunks == []  # Not enough for a full chunk yet


# ── Pipeline Integration (mocked) ────────────────────────────

class TestPipelineOrchestrator:
    @pytest.mark.asyncio
    async def test_translate_and_broadcast_called(self):
        """Verify translate_and_broadcast is triggered on final transcript."""
        from src.pipeline.orchestrator import TranslationPipeline, UtteranceContext
        from src.stt.soniox_client import Transcript

        mock_channel = AsyncMock()
        pipeline = TranslationPipeline(mock_channel)

        # Mock translate + tts
        pipeline._translator.translate = AsyncMock(return_value=MagicMock(
            translations={"hi": "नमस्ते"},
            source_text="Hello",
        ))
        pipeline._tts.synthesize_all = AsyncMock(return_value=[])
        mock_channel.publish_results = AsyncMock()

        ctx = UtteranceContext("test-utt-1")
        transcript = Transcript(
            text="Hello world",
            is_final=True,
            confidence=0.99,
            latency_ms=120.0,
            words=[],
        )

        await pipeline._on_transcript(transcript, ctx)

        pipeline._translator.translate.assert_called_once_with("Hello world")
        pipeline._tts.synthesize_all.assert_called_once()


# ── Channel Manager Tests ─────────────────────────────────────

class TestChannelManager:
    @pytest.mark.asyncio
    async def test_subscribe_unsubscribe(self):
        from src.streaming.channel_manager import ChannelManager

        mgr = ChannelManager()
        fake_ws = MagicMock()

        await mgr.subscribe(fake_ws, "hi")
        assert mgr.subscriber_count("hi") == 1

        await mgr.unsubscribe(fake_ws, "hi")
        assert mgr.subscriber_count("hi") == 0

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self):
        from src.streaming.channel_manager import ChannelManager

        mgr = ChannelManager()
        ws1, ws2, ws3 = MagicMock(), MagicMock(), MagicMock()

        await mgr.subscribe(ws1, "hi")
        await mgr.subscribe(ws2, "hi")
        await mgr.subscribe(ws3, "te")

        assert mgr.subscriber_count("hi") == 2
        assert mgr.subscriber_count("te") == 1

        counts = mgr.all_subscriber_counts()
        assert counts["hi"] == 2
        assert counts["te"] == 1
