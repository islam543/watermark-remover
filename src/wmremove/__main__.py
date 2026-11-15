"""Run a one-off cleanup or keep watching the drop folder."""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
from functools import cache
from pathlib import Path

from .batch import run_batch
from .detect import Template
from .inpaint import Lama
from .overlays import load_overlays
from .pipeline import Config, log, open_db, poll_once, resume


def main():
    parser = argparse.ArgumentParser(description="Remove the QatarSale, Torque Motors, Qatar Living and Mzad Qatar image overlays.")
    parser.add_argument("source", nargs="?", help="image file, folder, or link to an image, car listing, or showroom")
    parser.add_argument("-o", "--output", type=Path, help="output file for a single image or output folder for a batch")
    parser.add_argument("--download-only", action="store_true", help="save photos from a link without removing overlays")
    args = parser.parse_args()
    if args.output and not args.source:
        parser.error("--output requires an input file, folder, or link")
    if args.download_only and not args.source:
        parser.error("--download-only requires a link")

    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(asctime)s %(message)s")
    cfg = target = None
    if not args.download_only:
        cfg = Config.from_env()
        try:
            target = Template(cfg.template) if "WM_TEMPLATE" in os.environ or cfg.template.is_file() else load_overlays()
        except (OSError, ValueError) as exc:
            parser.exit(1, f"{exc}\n")

    @cache
    def model():
        log.info("loading the model")
        return Lama(cfg.device)

    def inpaint(rgb, mask):
        return model()(rgb, mask)

    if args.source:
        try:
            return run_batch(args.source, args.output, cfg, target, inpaint, download_only=args.download_only)
        except (OSError, ValueError) as exc:
            log.error("%s", exc)
            return 1

    db = open_db(cfg)
    stop = threading.Event()  # finish the current photo, then exit
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())

    try:
        resume(cfg, target, inpaint, db)
        log.info("watching %s", cfg.root / "in")
        sizes = {}
        while not stop.is_set():
            poll_once(cfg, target, inpaint, db, sizes)
            stop.wait(1.0)
    finally:
        db.close()
    log.info("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
