import cv2
import pytest

from synth import make_mark, make_photo, stamp
from wmremove.detect import Template, find
from wmremove.pipeline import Config

MIN_SCORE = Config.min_score


def template(tmp_path, **mark_options):
    mark = make_mark(**mark_options)
    cv2.imwrite(str(tmp_path / "mark.png"), mark)
    return mark, Template(tmp_path / "mark.png")


def gray(rgb):
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)


@pytest.mark.parametrize(
    "mark_options, x, y, scale, opacity",
    [
        ({"height": 40}, 850, 720, 0.8, 0.6),  # small mark in a corner
        ({"height": 40}, 30, 20, 1.3, 0.4),  # other corner, larger, fainter
        ({"height": 70, "angle": 30}, 150, 60, 0.9, 0.4),  # big faint diagonal mark across the photo
    ],
)
def test_finds_the_mark_wherever_it_is(tmp_path, mark_options, x, y, scale, opacity):
    mark, tpl = template(tmp_path, **mark_options)
    photo = stamp(make_photo(3), mark, x, y, scale, opacity)

    det = find(gray(photo), tpl)

    assert det.score >= MIN_SCORE
    assert abs(det.x - x) <= 4 and abs(det.y - y) <= 4
    assert abs(det.w - mark.shape[1] * scale) <= 6


@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_photo_without_the_mark_scores_below_the_threshold(tmp_path, seed):
    _, tpl = template(tmp_path, height=40)
    assert find(gray(make_photo(seed)), tpl).score < MIN_SCORE


def test_a_different_text_is_not_mistaken_for_the_mark(tmp_path):
    _, tpl = template(tmp_path, height=40)
    other = make_mark("OTHER WORDS", height=40)
    photo = stamp(make_photo(5), other, 700, 600, 1.0, 0.7)
    assert find(gray(photo), tpl).score < MIN_SCORE
