"""The real model. Slow, and downloads LaMa (about 200 MB) the first time."""
import cv2
import numpy as np
import pytest
from PIL import Image

from conftest import drop, files, run
from synth import make_mark, make_photo, stamp
from wmremove.detect import Template, build_mask, find
from wmremove.inpaint import Lama

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def lama():
    return Lama("cpu")


@pytest.mark.parametrize(
    "mark_options, x, y, scale, opacity",
    [
        ({"height": 40}, 800, 700, 1.0, 0.6),  # corner mark
        ({"height": 70, "angle": 30}, 150, 60, 0.9, 0.5),  # diagonal mark across the photo
    ],
)
def test_lama_removes_the_mark_and_touches_nothing_else(box, lama, mark_options, x, y, scale, opacity):
    mark = make_mark(**mark_options)
    cv2.imwrite(str(box.cfg.template), mark)
    box.tpl = Template(box.cfg.template)
    photo = stamp(make_photo(7), mark, x, y, scale, opacity)

    assert run(box, drop(box, "car.png", photo), inpaint=lama) == "clean"

    assert files(box, "clean") == ["car.png"]
    result = np.asarray(Image.open(box.root / "clean" / "car.png"))
    gray = cv2.cvtColor(photo, cv2.COLOR_RGB2GRAY)
    mask = build_mask(gray.shape, find(gray, box.tpl), box.tpl, max(2, round(0.003 * max(gray.shape))))
    assert np.array_equal(result[mask == 0], photo[mask == 0])
