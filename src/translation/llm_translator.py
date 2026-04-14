"""
translation/llm_translator.py — Groq-powered ultra-fast one-to-many translator.
Translates a single source text into ALL target languages in one LLM call.

Groq provides ~30-60ms inference latency for Llama 3 70B — critical for
hitting the 60ms end-to-end pipeline target.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Dict, List, Optional

import aiohttp

from src.config_loader import cfg, LanguageConfig
from src.logger import get_logger, log_latency

log = get_logger(__name__)


class TranslationResult:
    __slots__ = ("translations", "source_text", "latency_ms", "model_used")

    def __init__(
        self,
        translations: Dict[str, str],
        source_text: str,
        latency_ms: float,
        model_used: str,
    ) -> None:
        self.translations = translations
        self.source_text = source_text
        self.latency_ms = latency_ms
        self.model_used = model_used


_SYSTEM_PROMPT = """\
You are a professional real-time translator. Your task is to translate the given text into all requested target languages simultaneously.

Rules:
- Return ONLY a valid JSON object, no preamble, no explanation, no markdown fences
- Keys are ISO 639-1 language codes
- Values are accurate, natural-sounding translations
- Preserve tone, formality, and speaking style
- For code-mixed input (e.g. Hinglish), translate intent naturally
- If a language cannot be translated, use an empty string as value
"""


def _build_user_prompt(source_text: str, languages: List[LanguageConfig]) -> str:
    lang_list = ", ".join(f"{lang.name} ({lang.code})" for lang in languages)
    response_shape = ", ".join(f'"{lang.code}": "..."' for lang in languages)
    return (
        f'Translate the following {cfg.source.language_name} text into: {lang_list}.\n\n'
        f'Text: "{source_text}"\n\n'
        f"Respond only with JSON: {{{response_shape}}}"
    )


def _parse_json_from_response(raw: str) -> Optional[Dict[str, str]]:
    """
    Robustly extract JSON from LLM output.
    Handles: bare JSON, markdown fences, partial JSON, extra text.
    """
    text = raw.strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Extract JSON object using regex
    match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # Strip markdown fences and retry
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    log.warning("json_parse_failed", raw=raw[:200])
    return None


# ── Translation Cache for speculative dedup ─────────────────────
_translation_cache: Dict[str, TranslationResult] = {}
_CACHE_MAX_SIZE = 200


class LLMTranslator:
    """
    Sends one-to-many translation requests to Groq API (OpenAI-compatible).
    Groq runs Llama 3 70B with ~30-60ms inference latency.
    Maintains a persistent aiohttp session with connection pooling.
    """

    def __init__(self) -> None:
        self._cfg = cfg.apis.groq
        self._session: Optional[aiohttp.ClientSession] = None
        self._languages = cfg.enabled_languages
        self._url = f"{self._cfg.base_url}/chat/completions"
        self._inflight: Dict[str, asyncio.Task] = {}  # Dedup concurrent identical requests

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(
                limit=30,
                ttl_dns_cache=300,
                use_dns_cache=True,
                keepalive_timeout=120,  # Keep connections warm
                enable_cleanup_closed=True,
            )
            timeout = aiohttp.ClientTimeout(total=self._cfg.timeout_seconds)
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers={
                    "Authorization": f"Bearer {self._cfg.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._session

    async def translate(
        self,
        source_text: str,
        languages: Optional[List[LanguageConfig]] = None,
    ) -> TranslationResult:
        """
        Translate source_text into all enabled languages in a single LLM call.
        Uses Groq's OpenAI-compatible API for ~30-60ms inference.
        Includes request deduplication for speculative translation overlap.
        """
        target_langs = languages or self._languages
        if not target_langs:
            return TranslationResult({}, source_text, 0.0, self._cfg.model_id)

        # ── Cache check (for repeated speculative translations) ──
        cache_key = source_text.strip().lower()
        if cache_key in _translation_cache:
            cached = _translation_cache[cache_key]
            log.debug("translation_cache_hit", text=source_text[:30])
            return cached

        # ── Dedup: if identical request is in-flight, await it ──
        if cache_key in self._inflight:
            log.debug("translation_dedup", text=source_text[:30])
            try:
                return await self._inflight[cache_key]
            except Exception:
                pass  # Fall through to make a new request

        # Create the translation task
        task = asyncio.create_task(self._do_translate(source_text, target_langs, cache_key))
        self._inflight[cache_key] = task

        try:
            return await task
        finally:
            self._inflight.pop(cache_key, None)

    async def _do_translate(
        self,
        source_text: str,
        target_langs: List[LanguageConfig],
        cache_key: str,
    ) -> TranslationResult:
        """Execute the actual Groq API call."""
        start = time.perf_counter()

        user_prompt = _build_user_prompt(source_text, target_langs)

        # Groq uses OpenAI-compatible chat completions API
        payload = {
            "model": self._cfg.model_id,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": self._cfg.max_tokens,
            "temperature": self._cfg.temperature,
            "response_format": {"type": "json_object"},  # Force JSON output
            "stream": False,  # Non-streaming for simplicity; Groq is fast enough
        }

        session = await self._ensure_session()

        for attempt in range(cfg.pipeline.retry_attempts + 1):
            try:
                async with session.post(self._url, json=payload) as resp:
                    if resp.status == 429:
                        # Rate limited — brief backoff
                        retry_after = float(resp.headers.get("Retry-After", "0.5"))
                        log.warning("groq_rate_limited", retry_after=retry_after)
                        await asyncio.sleep(min(retry_after, 2.0))
                        continue

                    resp.raise_for_status()
                    body = await resp.json()

                    # Groq returns OpenAI-compatible response
                    raw_output = ""
                    choices = body.get("choices", [])
                    if choices:
                        raw_output = choices[0].get("message", {}).get("content", "")

                    translations = _parse_json_from_response(raw_output) or {}

                    # Fill in missing languages with empty string
                    for lang in target_langs:
                        if lang.code not in translations:
                            translations[lang.code] = ""

                    latency_ms = (time.perf_counter() - start) * 1000

                    # Log Groq-specific metrics
                    usage = body.get("usage", {})
                    log.info(
                        "translation_complete",
                        source_chars=len(source_text),
                        languages=len(translations),
                        latency_ms=round(latency_ms, 1),
                        groq_tokens=usage.get("total_tokens", 0),
                        groq_time_ms=round(
                            body.get("usage", {}).get("total_time", 0) * 1000, 1
                        ),
                    )

                    result = TranslationResult(
                        translations=translations,
                        source_text=source_text,
                        latency_ms=latency_ms,
                        model_used=self._cfg.model_id,
                    )

                    # Cache the result
                    if len(_translation_cache) >= _CACHE_MAX_SIZE:
                        # Evict oldest entries
                        keys = list(_translation_cache.keys())
                        for k in keys[:_CACHE_MAX_SIZE // 2]:
                            _translation_cache.pop(k, None)
                    _translation_cache[cache_key] = result

                    return result

            except aiohttp.ClientResponseError as exc:
                log.error("groq_api_error", status=exc.status, attempt=attempt)
                if attempt >= cfg.pipeline.retry_attempts:
                    raise
                await asyncio.sleep(cfg.pipeline.retry_delay_ms / 1000)

            except asyncio.TimeoutError:
                log.error("groq_timeout", attempt=attempt)
                if attempt >= cfg.pipeline.retry_attempts:
                    raise
                await asyncio.sleep(cfg.pipeline.retry_delay_ms / 1000)

        return TranslationResult({}, source_text, 0.0, self._cfg.model_id)

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
"""
translation/llm_translator.py — Groq-powered ultra-fast one-to-many translator.
"""
