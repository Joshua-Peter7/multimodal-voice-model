"""
main.py — Application entry point.
Run with: python main.py
Or with uvicorn for production: uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
"""

import platform

import uvicorn

from src.api.server import app
from src.config_loader import cfg
from src.logger import get_logger

log = get_logger(__name__)


def main() -> None:
    log.info(
        "starting_server",
        host=cfg.server.host,
        port=cfg.server.port,
        target_languages=[l.code for l in cfg.enabled_languages],
    )

    event_loop = "asyncio" if platform.system() == "Windows" else "uvloop"

    uvicorn.run(
        "src.api.server:app",
        host=cfg.server.host,
        port=cfg.server.port,
        reload=False,
        log_level=cfg.logging.level.lower(),
        ws_ping_interval=cfg.server.ping_interval_seconds,
        ws_ping_timeout=cfg.server.ping_timeout_seconds,
        loop=event_loop,     # uvloop is not available on Windows
        http="httptools",    # Fast HTTP parser
        workers=1,           # WebSocket state must stay in single process; use Redis for scaling
    )


if __name__ == "__main__":
    main()
