from __future__ import annotations

import logging
import signal
import threading

from .api import create_api_server
from .bot_ux import TelegramUxBot
from .config import load_config
from .db import Registry


LOG = logging.getLogger("hermes_rdp")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config()
    registry = Registry(
        config.db_path,
        config.port_start,
        config.port_end,
        config.command_timeout_seconds,
    )
    api_server = create_api_server(config, registry)
    bot = None
    if config.telegram_token and config.telegram_chat_id:
        bot = TelegramUxBot(config, registry)

    api_thread = threading.Thread(target=api_server.serve_forever, daemon=True)
    api_thread.start()
    if bot is not None:
        bot_thread = threading.Thread(target=bot.run, daemon=True)
        bot_thread.start()
    else:
        LOG.warning("Telegram is not configured; web/API control remains available")

    stop_event = threading.Event()

    def stop_handler(signum, frame):
        LOG.info("received signal %s", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)
    LOG.info("Hermes RDP started on HTTPS port %s", config.api_port)
    stop_event.wait()
    if bot is not None:
        bot.stop()
    api_server.shutdown()
    api_server.server_close()


if __name__ == "__main__":
    main()
