from types import SimpleNamespace

import cv2
import pytest
from PIL import Image

from synth import make_mark, make_photo, stamp
from wmremove.detect import Template
from wmremove.pipeline import Config, intake, open_db, process


def cheap_fill(rgb, mask):
    """Stand-in for LaMa so tests run fast. It proves the plumbing, not the quality."""
    return cv2.inpaint(rgb, mask, 3, cv2.INPAINT_TELEA)


@pytest.fixture
def box(tmp_path):
    """A fresh set of folders with a watermark template in place."""
    mark = make_mark()
    cv2.imwrite(str(tmp_path / "watermark.png"), mark)
    cfg = Config(root=tmp_path, template=tmp_path / "watermark.png")
    return SimpleNamespace(cfg=cfg, root=tmp_path, mark=mark, tpl=Template(cfg.template), db=open_db(cfg))


def marked_photo(box, seed=1, x=700, y=600, scale=1.0, opacity=0.6):
    return stamp(make_photo(seed), box.mark, x, y, scale, opacity)


def drop(box, name, rgb, **save_options):
    """Save a picture into in/ the way a user would drop it."""
    path = box.root / "in" / name
    Image.fromarray(rgb).save(path, **save_options)
    return path


def run(box, path, inpaint=cheap_fill):
    return process(intake(path, box.cfg, box.db), box.cfg, box.tpl, inpaint, box.db)


def files(box, folder):
    return sorted(p.name for p in (box.root / folder).iterdir())


def reason(box):
    return box.db.execute("SELECT reason FROM photos ORDER BY id DESC").fetchone()[0]
