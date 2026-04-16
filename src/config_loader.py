"""
config_loader.py — Loads config.yaml with environment variable substitution.
All modules import settings exclusively from here.
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from dotenv import load_dotenv

load_dotenv()

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.yaml"
_lock = threading.Lock()
_config_cache: Optional["AppConfig"] = None


# ── Dataclasses mirror config.yaml structure ────────────────

@dataclass
class SonioxConfig:
    api_key: str
    model: str
    sample_rate: int
    num_audio_channels: int
    include_nonfinal: bool
    max_alternatives: int
    language_code: Optional[str] = None


@dataclass
class GroqConfig:
    api_key: str
    base_url: str
    model_id: str
    max_tokens: int
    temperature: float
    timeout_seconds: int


@dataclass
class ElevenLabsConfig:
    api_key: str
    model_id: str
    output_format: str
    optimize_streaming_latency: int
    stream_chunk_size: int
    use_websocket: bool
    ws_url: str


@dataclass
class ApisConfig:
    soniox: SonioxConfig
    groq: GroqConfig
    elevenlabs: ElevenLabsConfig


@dataclass
class SourceConfig:
    language_code: str
    language_name: str


@dataclass
class LanguageConfig:
    code: str
    name: str
    voice_id: str
    stability: float
    similarity_boost: float
    enabled: bool


@dataclass
class VADConfig:
    enabled: bool
    aggressiveness: int
    silence_threshold_ms: int
    speech_threshold_ms: int
    energy_threshold: float


@dataclass
class NoiseSuppression:
    enabled: bool
    intensity: float


@dataclass
class AudioConfig:
    sample_rate: int
    channels: int
    bit_depth: int
    chunk_duration_ms: int
    bypass_vad: bool
    vad: VADConfig
    noise_suppression: NoiseSuppression


@dataclass
class PipelineConfig:
    speculative_translation: bool
    partial_min_chars: int
    speculative_interval_ms: int
    final_confirm_delay_ms: int
    max_tts_concurrency: int
    target_latency_ms: int
    retry_attempts: int
    retry_delay_ms: int
    stream_tts_chunks: bool
    parallel_lang_processing: bool


@dataclass
class ModerationConfig:
    enabled: bool
    strategy: str
    replacement_text: str
    blocked_words: List[str]
    severity_threshold: float
    moderate_translations: bool


@dataclass
class ServerConfig:
    host: str
    port: int
    ws_path: str
    ws_speaker_path: str
    ws_listener_path: str
    cors_origins: List[str]
    max_connections: int
    ping_interval_seconds: int
    ping_timeout_seconds: int


@dataclass
class RedisConfig:
    host: str
    port: int
    db: int
    password: str
    channel_prefix: str
    max_connections: int


@dataclass
class LoggingConfig:
    level: str
    format: str
    log_latency: bool
    log_transcripts: bool


@dataclass
class MetricsConfig:
    enabled: bool
    prometheus_port: int
    collect_interval_seconds: int


@dataclass
class AppConfig:
    apis: ApisConfig
    source: SourceConfig
    languages: List[LanguageConfig]
    audio: AudioConfig
    pipeline: PipelineConfig
    moderation: ModerationConfig
    server: ServerConfig
    redis: RedisConfig
    logging: LoggingConfig
    metrics: MetricsConfig

    @property
    def enabled_languages(self) -> List[LanguageConfig]:
        return [lang for lang in self.languages if lang.enabled]


# ── Loader ──────────────────────────────────────────────────

def _substitute_env(value: Any) -> Any:
    """Recursively substitute ${ENV_VAR} placeholders in config values."""
    if isinstance(value, str):
        def replace(match: re.Match) -> str:
            var_name = match.group(1)
            return os.environ.get(var_name, "")
        return re.sub(r"\$\{([^}]+)\}", replace, value)
    if isinstance(value, dict):
        return {k: _substitute_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute_env(item) for item in value]
    return value


def _build_config(raw: Dict[str, Any]) -> AppConfig:
    a = raw["apis"]
    s = a["soniox"]
    g = a["groq"]
    e = a["elevenlabs"]

    audio_raw = raw["audio"]
    vad_raw = audio_raw["vad"]
    ns_raw = audio_raw["noise_suppression"]

    languages = [
        LanguageConfig(**lang) for lang in raw["languages"]
    ]

    return AppConfig(
        apis=ApisConfig(
            soniox=SonioxConfig(**s),
            groq=GroqConfig(**g),
            elevenlabs=ElevenLabsConfig(**e),
        ),
        source=SourceConfig(**raw["source"]),
        languages=languages,
        audio=AudioConfig(
            sample_rate=audio_raw["sample_rate"],
            channels=audio_raw["channels"],
            bit_depth=audio_raw["bit_depth"],
            chunk_duration_ms=audio_raw["chunk_duration_ms"],
            bypass_vad=audio_raw.get("bypass_vad", False),
            vad=VADConfig(**vad_raw),
            noise_suppression=NoiseSuppression(**ns_raw),
        ),
        pipeline=PipelineConfig(**raw["pipeline"]),
        moderation=ModerationConfig(**raw["moderation"]),
        server=ServerConfig(**raw["server"]),
        redis=RedisConfig(**raw["redis"]),
        logging=LoggingConfig(**raw["logging"]),
        metrics=MetricsConfig(**raw["metrics"]),
    )


def load_config(path: Path = _CONFIG_PATH) -> AppConfig:
    """Load and return the global AppConfig. Cached after first call."""
    global _config_cache
    with _lock:
        if _config_cache is not None:
            return _config_cache
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        raw = _substitute_env(raw)
        _config_cache = _build_config(raw)
        return _config_cache


def reload_config() -> AppConfig:
    """Force-reload config from disk (useful for hot-reload)."""
    global _config_cache
    with _lock:
        _config_cache = None
    return load_config()


# Singleton accessor
cfg: AppConfig = load_config()
