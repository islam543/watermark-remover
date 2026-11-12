"""The folder service: `python -m wmremove`. Stop it with Ctrl+C."""
from __future__ import annotations

import logging
import signal
import sys
import threading

from .detect import Template
from .inpaint import Lama
from .pipeline import Config, log, open_db, poll_once, resume


def main():
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(asctime)s %(message)s")
    cfg = Config.from_env()
    try:
        tpl = Template(cfg.template)
    except FileNotFoundError as exc:
        sys.exit(f"{exc}\nPut a picture of your watermark there, or set WM_TEMPLATE.")
    db = open_db(cfg)
    log.info("loading the model")
    inpaint = Lama(cfg.device)

    stop = threading.Event()  # finish the current photo, then exit
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())

    resume(cfg, tpl, inpaint, db)
    log.info("watching %s", cfg.root / "in")
    sizes = {}
    while not stop.is_set():
        poll_once(cfg, tpl, inpaint, db, sizes)
        stop.wait(1.0)
    log.info("stopped")


if __name__ == "__main__":
    main()
