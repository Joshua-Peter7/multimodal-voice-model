"""
metrics.py — Prometheus metrics for the translation pipeline.
Exposes latency histograms, counters, and gauges on /metrics.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, start_http_server

from src.config_loader import cfg
from src.logger import get_logger

log = get_logger(__name__)

# ── Metric Definitions ───────────────────────────────────────
buckets = cfg.metrics.latency_buckets or [100, 200, 500, 1000, 2000, 5000]

pipeline_latency = Histogram(
    "translation_pipeline_latency_ms",
    "End-to-end pipeline latency in milliseconds",
    buckets=buckets,
)

stt_latency = Histogram(
    "stt_latency_ms",
    "Soniox STT latency per utterance",
    buckets=buckets,
)

translation_latency = Histogram(
    "llm_translation_latency_ms",
    "LLM translation latency per utterance",
    buckets=buckets,
)

tts_latency = Histogram(
    "tts_synthesis_latency_ms",
    "ElevenLabs TTS latency per utterance",
    buckets=buckets,
)

utterances_total = Counter(
    "utterances_total",
    "Total utterances processed",
)

moderation_flags_total = Counter(
    "moderation_flags_total",
    "Total utterances flagged by content moderation",
)

pipeline_errors_total = Counter(
    "pipeline_errors_total",
    "Total pipeline errors by stage",
    ["stage"],
)

active_listeners = Gauge(
    "active_listeners",
    "Number of active listener WebSocket connections",
    ["lang_code"],
)

speaker_connected = Gauge(
    "speaker_connected",
    "1 if a speaker is currently broadcasting, 0 otherwise",
)


def record_pipeline(
    total_ms: float,
    stt_ms: float,
    translation_ms: float,
    tts_ms: float,
    flagged: bool,
) -> None:
    pipeline_latency.observe(total_ms)
    stt_latency.observe(stt_ms)
    translation_latency.observe(translation_ms)
    tts_latency.observe(tts_ms)
    utterances_total.inc()
    if flagged:
        moderation_flags_total.inc()


def start_metrics_server() -> None:
    if cfg.metrics.enabled:
        start_http_server(cfg.metrics.prometheus_port)
        log.info("metrics_server_started", port=cfg.metrics.prometheus_port)
