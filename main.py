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
from src.metrics import start_metrics_server

log = get_logger(__name__)


def main() -> None:
    # Start Prometheus metrics server
    start_metrics_server()

    log.info(
        "starting_server",
        host=cfg.server.host,
        port=cfg.server.port,
        target_languages=[l.code for l in cfg.enabled_languages],
    )

    event_loop = "asyncio" if platform.system() == "Windows" else "uvloop"

    try:
        uvicorn.run(
            "src.api.server:app",
            host=cfg.server.host,
            port=cfg.server.port,
            reload=False,
            log_level=cfg.logging.level.lower(),
            ws_ping_interval=cfg.server.ping_interval_seconds,
            ws_ping_timeout=cfg.server.ping_timeout_seconds,
            loop=event_loop,
            http="httptools",
            workers=1,
        )
    except Exception as e:
        import traceback
        print(f"FATAL SERVER ERROR: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    main()
