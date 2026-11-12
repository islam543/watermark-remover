import cv2
import numpy as np
from PIL import Image

from conftest import cheap_fill, drop, files, marked_photo, reason, run
from synth import make_photo
from wmremove.detect import build_mask, find
from wmremove.pipeline import intake, poll_once, resume


def mask_for(box, rgb):
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    det = find(gray, box.tpl)
    return build_mask(gray.shape, det, box.tpl, max(2, round(0.003 * max(gray.shape))))


def test_marked_png_comes_out_clean_and_only_masked_pixels_change(box):
    photo = marked_photo(box)
    path = drop(box, "car.png", photo)
    dropped_bytes = path.read_bytes()

    assert run(box, path) == "clean"

    assert files(box, "in") == [] and files(box, "needs-attention") == []
    assert files(box, "clean") == ["car.png"]
    assert (box.root / "originals" / "car.png").read_bytes() == dropped_bytes
    result = np.asarray(Image.open(box.root / "clean" / "car.png"))
    mask = mask_for(box, photo)
    assert result.shape == photo.shape
    assert np.array_equal(result[mask == 0], photo[mask == 0])  # untouched outside the mark
    assert not np.array_equal(result[mask > 0], photo[mask > 0])  # changed under it


def test_photo_without_the_mark_is_held_back_untouched(box):
    path = drop(box, "plain.png", make_photo(2))
    dropped_bytes = path.read_bytes()

    assert run(box, path) == "needs-attention"

    assert reason(box) == "watermark not found"
    assert files(box, "clean") == []
    assert (box.root / "needs-attention" / "plain.png").read_bytes() == dropped_bytes


def test_failed_removal_is_never_delivered_as_clean(box):
    path = drop(box, "car.png", marked_photo(box))

    assert run(box, path, inpaint=lambda rgb, mask: rgb) == "needs-attention"

    assert reason(box) == "watermark still visible after removal"
    assert files(box, "clean") == []


def test_jpeg_stays_a_jpeg_of_the_same_size(box):
    photo = marked_photo(box)
    path = drop(box, "car.jpg", photo, quality=90)
    decoded = np.asarray(Image.open(path))

    assert run(box, path) == "clean"

    with Image.open(box.root / "clean" / "car.jpg") as out:
        assert out.format == "JPEG" and out.size == (photo.shape[1], photo.shape[0])
        result = np.asarray(out)
    outside = mask_for(box, decoded) == 0
    drift = np.abs(result[outside].astype(int) - decoded[outside].astype(int)).mean()
    assert drift < 1.0  # re-saving a JPEG is not bit-exact, but it must stay tiny


def test_unreadable_file_is_held_back_and_the_service_survives(box):
    path = box.root / "in" / "notes.txt"
    path.write_text("not a picture")

    assert run(box, path) == "needs-attention"
    assert reason(box).startswith("error")
    assert files(box, "needs-attention") == ["notes.txt"]


def test_file_is_only_picked_up_once_it_has_stopped_growing(box):
    drop(box, "car.png", marked_photo(box))
    sizes = {}

    poll_once(box.cfg, box.tpl, cheap_fill, box.db, sizes)
    assert files(box, "in") == ["car.png"]  # first look: might still be copying

    poll_once(box.cfg, box.tpl, cheap_fill, box.db, sizes)
    assert files(box, "in") == [] and files(box, "clean") == ["car.png"]


def test_photo_received_before_a_crash_is_finished_on_restart(box):
    intake(drop(box, "car.png", marked_photo(box)), box.cfg, box.db)  # recorded, never processed

    resume(box.cfg, box.tpl, cheap_fill, box.db)

    assert files(box, "clean") == ["car.png"]


def test_same_file_name_twice_keeps_both_originals(box):
    run(box, drop(box, "car.png", marked_photo(box, seed=1)))
    run(box, drop(box, "car.png", marked_photo(box, seed=2)))

    assert files(box, "originals") == ["car-1.png", "car.png"]
    assert files(box, "clean") == ["car-1.png", "car.png"]
