"""One photo end to end: find the mark, remove it, check the result, file it."""
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, JpegImagePlugin

from .detect import build_mask, find, score_at
from .inpaint import remove

log = logging.getLogger("wmremove")
FOLDERS = ("in", "clean", "needs-attention", "originals")


@dataclass(frozen=True)
class Config:
    root: Path
    template: Path
    min_score: float = 0.65  # below this the watermark counts as not found
    max_residual: float = 0.35  # at or above this after removal, the mark is still visible
    min_share: float = 0.08  # smallest watermark width, as a share of photo width
    max_share: float = 1.0
    mask_grow: int = 0  # pixels added around the letters; 0 picks it from photo size
    max_mask_share: float = 0.25  # refuse if the mask covers more of the photo than this
    device: str = "cpu"

    @classmethod
    def from_env(cls):
        env = os.environ.get
        root = Path(env("WM_ROOT", ".")).resolve()
        return cls(
            root=root,
            template=Path(env("WM_TEMPLATE", str(root / "watermark.png"))),
            min_score=float(env("WM_MIN_SCORE", cls.min_score)),
            max_residual=float(env("WM_MAX_RESIDUAL", cls.max_residual)),
            min_share=float(env("WM_MIN_SHARE", cls.min_share)),
            max_share=float(env("WM_MAX_SHARE", cls.max_share)),
            mask_grow=int(env("WM_MASK_GROW", cls.mask_grow)),
            max_mask_share=float(env("WM_MAX_MASK_SHARE", cls.max_mask_share)),
            device=env("WM_DEVICE", cls.device),
        )


def open_db(cfg):
    for folder in FOLDERS:
        (cfg.root / folder).mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(cfg.root / "wmremove.sqlite")
    db.execute(
        "CREATE TABLE IF NOT EXISTS photos (id INTEGER PRIMARY KEY, name TEXT, original TEXT,"
        " status TEXT, reason TEXT, score REAL, residual REAL, seconds REAL,"
        " received_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    return db


def _free(path):
    """The path itself, or the same name with -1, -2... if it is taken."""
    out, n = path, 0
    while out.exists():
        n += 1
        out = path.with_name(f"{path.stem}-{n}{path.suffix}")
    return out


def intake(path, cfg, db):
    """Move a dropped file into originals/ and record it. Returns the row id."""
    original = _free(cfg.root / "originals" / path.name)
    shutil.move(str(path), original)
    row = db.execute(
        "INSERT INTO photos (name, original, status) VALUES (?, ?, 'received')",
        (original.name, str(original)),
    )
    db.commit()
    return row.lastrowid


def process(row_id, cfg, tpl, inpaint, db):
    """Handle one recorded photo. Returns 'clean' or 'needs-attention'."""
    name, original = db.execute("SELECT name, original FROM photos WHERE id=?", (row_id,)).fetchone()
    start = time.monotonic()
    score = residual = None
    try:
        status, reason, score, residual = _run(Path(original), cfg, tpl, inpaint)
    except Exception as exc:  # one bad file must not stop the service
        log.exception("failed on %s", name)
        status, reason = "needs-attention", f"error: {exc}"
    if status == "needs-attention":
        shutil.copy2(original, cfg.root / "needs-attention" / name)
    seconds = round(time.monotonic() - start, 2)
    db.execute(
        "UPDATE photos SET status=?, reason=?, score=?, residual=?, seconds=? WHERE id=?",
        (status, reason, score, residual, seconds, row_id),
    )
    db.commit()
    log.info("%s -> %s%s (score=%s residual=%s %.1fs)", name, status, f": {reason}" if reason else "", score, residual, seconds)
    return status


def _run(original, cfg, tpl, inpaint):
    with Image.open(original) as im:
        im.load()
        fmt, info = im.format, dict(im.info)
        jpeg = fmt in ("JPEG", "MPO")
        tables = (im.quantization, JpegImagePlugin.get_sampling(im)) if jpeg else None
        alpha = im.getchannel("A") if "A" in im.getbands() else None
        rgb = np.asarray(im.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    det = find(gray, tpl, cfg.min_share, cfg.max_share)
    if det is None or det.score < cfg.min_score:
        return "needs-attention", "watermark not found", det.score if det else None, None
    grow = cfg.mask_grow or max(2, round(0.003 * max(gray.shape)))
    mask = build_mask(gray.shape, det, tpl, grow)
    if mask.mean() / 255 > cfg.max_mask_share:
        return "needs-attention", "watermark covers too much of the photo", det.score, None

    out = remove(rgb, mask, inpaint)
    residual = score_at(cv2.cvtColor(out, cv2.COLOR_RGB2GRAY), tpl, det)
    if residual >= cfg.max_residual:
        return "needs-attention", "watermark still visible after removal", det.score, residual

    _save(out, alpha, cfg.root / "clean" / original.name, "JPEG" if jpeg else fmt, info, tables)
    return "clean", None, det.score, residual


def _save(rgb, alpha, dest, fmt, info, tables):
    out = Image.fromarray(rgb)
    if alpha is not None:
        out.putalpha(alpha)
    keep = {k: info[k] for k in ("exif", "icc_profile", "dpi") if k in info}
    tmp = dest.with_name(dest.name + ".part")  # never expose a half-written file
    try:
        if tables is None:
            out.save(tmp, format=fmt, **keep)
        else:  # reuse the photo's own JPEG tables so untouched areas barely change
            out.save(tmp, format=fmt, qtables=tables[0], subsampling=tables[1], **keep)
    except (ValueError, OSError):
        out.save(tmp, format=fmt, quality=95, **keep)
    tmp.replace(dest)


def resume(cfg, tpl, inpaint, db):
    """Finish photos that were received but not completed before a restart."""
    for (row_id,) in db.execute("SELECT id FROM photos WHERE status='received'").fetchall():
        process(row_id, cfg, tpl, inpaint, db)


def poll_once(cfg, tpl, inpaint, db, sizes):
    """Look at in/ once. A file is handled only when its size has stopped changing
    since the previous look, so a file still being copied is left alone."""
    for path in sorted((cfg.root / "in").iterdir()):
        if path.name.startswith(".") or not path.is_file():
            continue
        size = path.stat().st_size
        if size > 0 and sizes.get(path) == size:
            del sizes[path]
            process(intake(path, cfg, db), cfg, tpl, inpaint, db)
        else:
            sizes[path] = size
