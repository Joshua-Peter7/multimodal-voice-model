"""
moderation/content_moderator.py — Content safety filter for transcripts and translations.
Supports block, filter, and flag strategies configurable from config.yaml.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Optional

from src.config_loader import cfg
from src.logger import get_logger

log = get_logger(__name__)

# ── Built-in profanity list (extend in config.yaml blocked_words) ───────────
_BUILTIN_BLOCKED: list[str] = [
    # Add baseline words here; users extend via config.yaml
]


@dataclass
class ModerationResult:
    text: str
    flagged: bool
    strategy_applied: str
    matched_words: list[str]


class ContentModerator:
    """
    Screens text for offensive or unsafe content.
    Strategy is set in config.yaml:
      - "block"  → raises ValueError, caller should drop the message
      - "filter" → replaces offending words with replacement_text
      - "flag"   → passes text through but sets flagged=True
    """

    def __init__(self) -> None:
        self._cfg = cfg.moderation
        self._blocked: list[re.Pattern] = []

        if self._cfg.enabled:
            words = list(set(_BUILTIN_BLOCKED + (self._cfg.blocked_words or [])))
            for word in words:
                try:
                    self._blocked.append(
                        re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE)
                    )
                except re.error:
                    log.warning("bad_regex", word=word)

    def screen(self, text: str) -> ModerationResult:
        """Screen a single text string and return ModerationResult."""
        if not self._cfg.enabled or not text:
            return ModerationResult(text, False, "none", [])

        matched: list[str] = []
        for pattern in self._blocked:
            if pattern.search(text):
                matched.append(pattern.pattern)

        if not matched:
            return ModerationResult(text, False, "none", [])

        strategy = self._cfg.strategy

        if strategy == "block":
            log.warning("content_blocked", matched=matched)
            raise ValueError(f"Content blocked: {matched}")

        elif strategy == "filter":
            filtered = text
            for pattern in self._blocked:
                filtered = pattern.sub(self._cfg.replacement_text, filtered)
            log.info("content_filtered", matched=matched)
            return ModerationResult(filtered, True, "filter", matched)

        else:  # "flag"
            log.info("content_flagged", matched=matched)
            return ModerationResult(text, True, "flag", matched)

    def screen_translations(
        self, translations: Dict[str, str]
    ) -> tuple[Dict[str, str], bool]:
        """
        Screen all translations in a batch.
        Returns (cleaned_translations, any_flagged).
        """
        if not self._cfg.moderate_translations:
            return translations, False

        cleaned: Dict[str, str] = {}
        any_flagged = False

        for lang_code, text in translations.items():
            try:
                result = self.screen(text)
                cleaned[lang_code] = result.text
                if result.flagged:
                    any_flagged = True
            except ValueError:
                # "block" strategy: replace with empty
                cleaned[lang_code] = ""
                any_flagged = True

        return cleaned, any_flagged
