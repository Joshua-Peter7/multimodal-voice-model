"""
tests/test_translation.py — Tests for the LLM translation engine.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.translation.llm_translator import (
    LLMTranslator,
    TranslationResult,
    _parse_json_from_response,
    _build_llama_prompt,
    _build_user_prompt,
)
from src.config_loader import LanguageConfig


# ── Sample data ───────────────────────────────────────────────

SAMPLE_LANGS = [
    LanguageConfig("hi", "Hindi",   "v_hi", 0.5, 0.75, True),
    LanguageConfig("te", "Telugu",  "v_te", 0.5, 0.75, True),
    LanguageConfig("ta", "Tamil",   "v_ta", 0.5, 0.75, True),
]

SAMPLE_TRANSLATIONS = {
    "hi": "नमस्ते, आप कैसे हैं?",
    "te": "హలో, మీరు ఎలా ఉన్నారు?",
    "ta": "வணக்கம், நீங்கள் எப்படி இருக்கிறீர்கள்?",
}


# ── Prompt builder tests ──────────────────────────────────────

class TestPromptBuilder:
    def test_all_languages_in_prompt(self):
        prompt = _build_user_prompt("Hello there", SAMPLE_LANGS)
        assert "Hindi" in prompt
        assert "Telugu" in prompt
        assert "Tamil" in prompt
        assert "Hello there" in prompt

    def test_llama_format(self):
        prompt = _build_llama_prompt("Test input", SAMPLE_LANGS)
        assert "<|begin_of_text|>" in prompt
        assert "<|start_header_id|>system<|end_header_id|>" in prompt
        assert "<|start_header_id|>user<|end_header_id|>" in prompt
        assert "<|start_header_id|>assistant<|end_header_id|>" in prompt
        assert prompt.endswith("{")  # Primed for JSON

    def test_language_codes_in_prompt(self):
        prompt = _build_user_prompt("Hi", SAMPLE_LANGS)
        for lang in SAMPLE_LANGS:
            assert lang.code in prompt


# ── JSON parsing tests ────────────────────────────────────────

class TestJsonParsing:
    def test_valid_json(self):
        raw = json.dumps(SAMPLE_TRANSLATIONS)
        result = _parse_json_from_response(raw)
        assert result == SAMPLE_TRANSLATIONS

    def test_primed_brace_added(self):
        # Simulate model output without leading { (we prime with it)
        raw = '"hi": "नमस्ते", "te": "హలో"}'
        result = _parse_json_from_response(raw)
        assert result is not None
        assert "hi" in result

    def test_markdown_fence_stripped(self):
        raw = '```json\n{"hi": "नमस्ते"}\n```'
        result = _parse_json_from_response(raw)
        assert result == {"hi": "नमस्ते"}

    def test_extra_text_around_json(self):
        raw = 'Sure! Here are the translations:\n{"hi": "नमस्ते"}\nHope that helps!'
        result = _parse_json_from_response(raw)
        assert result is not None
        assert result.get("hi") == "नमस्ते"

    def test_garbage_returns_none(self):
        result = _parse_json_from_response("I cannot translate this.")
        assert result is None

    def test_empty_string(self):
        result = _parse_json_from_response("")
        assert result is None

    def test_nested_json_not_confused(self):
        raw = '{"hi": "hello", "te": "world"}'
        result = _parse_json_from_response(raw)
        assert result["hi"] == "hello"
        assert result["te"] == "world"


# ── LLMTranslator tests ───────────────────────────────────────

class TestLLMTranslator:
    @pytest.mark.asyncio
    async def test_successful_translation(self):
        translator = LLMTranslator()
        mock_response = [{"generated_text": json.dumps(SAMPLE_TRANSLATIONS)}]

        with patch.object(translator, "_ensure_session") as mock_session:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock(
                status=200,
                raise_for_status=MagicMock(),
                json=AsyncMock(return_value=mock_response),
            ))
            mock_ctx.__aexit__ = AsyncMock(return_value=False)

            mock_http = AsyncMock()
            mock_http.post = MagicMock(return_value=mock_ctx)
            mock_session.return_value = mock_http

            result = await translator.translate("Hello, how are you?", SAMPLE_LANGS)

        assert isinstance(result, TranslationResult)
        assert result.source_text == "Hello, how are you?"

        await translator.close()

    @pytest.mark.asyncio
    async def test_missing_lang_filled_with_empty(self):
        """If LLM omits a language, it should be filled with empty string."""
        translator = LLMTranslator()
        partial = {"hi": "नमस्ते"}  # Missing te and ta

        mock_response = [{"generated_text": json.dumps(partial)}]

        with patch.object(translator, "_ensure_session") as mock_session:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock(
                status=200,
                raise_for_status=MagicMock(),
                json=AsyncMock(return_value=mock_response),
            ))
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_http = AsyncMock()
            mock_http.post = MagicMock(return_value=mock_ctx)
            mock_session.return_value = mock_http

            result = await translator.translate("Hello", SAMPLE_LANGS)

        # Missing languages should be present as empty strings
        assert "te" in result.translations
        assert "ta" in result.translations
        assert result.translations["te"] == ""
        assert result.translations["ta"] == ""

        await translator.close()

    @pytest.mark.asyncio
    async def test_close_without_session(self):
        """close() should not raise if session was never opened."""
        translator = LLMTranslator()
        await translator.close()
