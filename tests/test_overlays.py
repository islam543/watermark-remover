import json
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError

import cv2
import numpy as np
from PIL import Image

from conftest import cheap_fill
from synth import make_mark, stamp
from wmremove import batch
from wmremove.detect import Detection, score_at
from wmremove.overlays import load_overlays, matches_overlay
from wmremove.pipeline import Config


def test_folder_removes_multiple_known_overlays_and_preserves_other_text(tmp_path):
    source = tmp_path / "incoming"
    source.mkdir()
    cfg = Config(tmp_path, tmp_path / "watermark.png")
    targets = load_overlays()
    with np.load(Path(batch.__file__).with_name("overlay-mattes.npz")) as mattes:
        torque = mattes["torque"][..., [2, 1, 0, 3]]
        living = mattes["qatar_living"][..., [2, 1, 0, 3]]
    base = np.full((420, 700, 3), 175, np.uint8)
    unrelated = make_mark("OTHER TEXT", height=30)
    base = stamp(base, unrelated, 180, 160, 1, 0.8)
    photo = stamp(base, torque, 490, 11, 0.78, 0.95)
    photo = stamp(photo, living, 32, 340, 0.83, 0.5)
    Image.fromarray(photo).save(source / "marked.png")
    Image.fromarray(base).save(source / "plain.png")
    original = (source / "marked.png").read_bytes()

    output = source / "results"
    assert batch.run_batch(str(source), output, cfg, targets, cheap_fill) == 1
    assert (source / "marked.png").read_bytes() == original
    assert sorted(p.name for p in output.iterdir()) == ["marked.png"]
    with Image.open(output / "marked.png") as im:
        cleaned = np.asarray(im)
    assert np.array_equal(cleaned[125:250], base[125:250])
    assert np.max(cv2.absdiff(cleaned, base)) <= 8


def test_qatarsale_can_confirm_a_weak_match_on_a_busy_background():
    overlay = load_overlays().designs[0]
    opacity = overlay.template.alpha.astype(np.float32) / 255 * 0.29
    h, w = opacity.shape
    original = np.full((h + 50, w + 50), 125, np.uint8)
    rng = np.random.default_rng(323)
    for _ in range(85):
        x, y = rng.integers((25, 25), (w + 25, h + 25))
        cv2.line(original, (x, y), (x + 90, y + 55), int(rng.choice([3, 255])), 3)
    marked = original.copy()
    area = np.s_[25:25 + h, 25:25 + w]
    marked[area] = np.rint(original[area] * (1 - opacity) + 255 * opacity)

    hint = Detection(25, 25, w, h, 1, 0)
    marked_score = score_at(marked, overlay.template, hint)
    assert 0 < marked_score < overlay.min_score
    assert matches_overlay(marked, overlay, Detection(25, 25, w, h, 1, marked_score))
    assert not matches_overlay(original, overlay, hint)


def test_qatar_living_confirms_partial_lettering_in_the_gallery_corner():
    overlay = load_overlays().designs[2]
    opacity = overlay.template.alpha.astype(np.float32) / 255 * 0.6
    h, w = opacity.shape
    original = np.full((675, 900), 50, np.uint8)
    x, y = original.shape[1] - w - 5, original.shape[0] - h - 5
    original[:, x + w // 2:] = 255
    area = np.s_[y:y + h, x:x + w]
    marked = original.copy()
    marked[area] = np.rint(original[area] * (1 - opacity) + 255 * opacity)

    weak_match = Detection(x, y, w, h, 1, 0.48)
    assert matches_overlay(marked, overlay, weak_match)
    assert not matches_overlay(original, overlay, weak_match)
    assert not matches_overlay(
        np.roll(marked, -100, axis=0), overlay, Detection(x, y - 100, w, h, 1, 0.48)
    )


def test_link_prefers_listing_gallery_and_continues_after_failed_download(tmp_path, monkeypatch):
    listing = "https://example.org/listing"
    page = b"""
        <meta property="og:image" content="/thumbnail.jpg">
        <div data-page='{"props":{"ads":{"productImages":["/first.png","/missing.png","/last.png"]}}}'></div>
    """
    photo = BytesIO()
    Image.new("RGB", (10, 10)).save(photo, format="PNG")

    def fetch(url):
        if url == listing:
            return url, "text/html", page
        if url == "https://example.org/missing.png":
            raise OSError("download failed")
        assert url != "https://example.org/thumbnail.jpg"
        return url, "image/png", photo.getvalue()

    processed = []

    def process(src, dest, cfg, target, inpaint):
        processed.append((src.name, dest.name))
        return True

    monkeypatch.setattr(batch, "_read_url", fetch)
    monkeypatch.setattr(batch, "_run_image", process)
    assert batch.run_batch(listing, tmp_path / "clean", None, None, None) == 1
    assert processed == [("first.png", "first.png"), ("last.png", "last.png")]


def test_retries_a_timed_out_image_link(monkeypatch):
    url = "https://example.org/photo.jpg"
    attempts = []

    def download(request):
        attempts.append(request.full_url)
        if len(attempts) == 1:
            raise URLError(TimeoutError())
        return url, "image/jpeg", b"photo data"

    monkeypatch.setattr(batch, "_download", download)
    assert batch._read_url(url) == (url, "image/jpeg", b"photo data")
    assert attempts == [url, url]


def test_downloads_qatar_living_gallery_without_running_cleanup(tmp_path, monkeypatch):
    listing = "https://www.qatarliving.com/en/vehicles/cars/123_test"
    media = "https://qlv-media-prod.qatarliving.com/ad-images-output/prod/test/"
    first = media + "front+side.JPG"
    second = media + "rear.JPG"
    first_large = media + "thumbnail/front%2Bside_900x675.webp"
    second_large = media + "thumbnail/rear_900x675.webp"
    metadata = json.dumps({"@type": ["Car", "Product"], "image": [{"url": first}, {"url": second}]})
    page = f'<script type="application/ld+json">{metadata}</script>'.encode()
    photo = BytesIO()
    Image.new("RGB", (10, 10)).save(photo, format="PNG")
    attempts = []

    def fetch(url):
        attempts.append(url)
        if url == listing:
            return url, "text/html", page
        if url == second_large:
            raise HTTPError(url, 404, "missing gallery version", {}, None)
        assert url in (first_large, second)
        return url, "image/png", photo.getvalue()

    monkeypatch.setattr(batch, "_read_url", fetch)
    output = tmp_path / "photos"
    assert batch.run_batch(listing, output, None, None, None, download_only=True) == 0
    assert attempts == [listing, first_large, second_large, second]
    assert {p.name: p.read_bytes() for p in output.iterdir()} == {
        "front+side_900x675.png": photo.getvalue(),
        "rear.png": photo.getvalue(),
    }


def test_reverses_the_faint_tilted_stamp_without_erasing_dashboard_text():
    stamp = load_overlays().tilted_torque
    photo = np.full((337, 600, 3), (52, 44, 42), np.uint8)
    cv2.putText(photo, "DASHBOARD", (148, 200), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (235, 232, 230), 2)
    assert stamp.reverse(photo) is None

    added = np.einsum("ihw,ic->hwc", stamp.alpha, stamp.colors)
    marked = np.rint(photo * (1 - stamp.alpha.sum(axis=0)[..., None]) + added).astype(np.uint8)
    restored = stamp.reverse(marked)

    assert restored is not None
    assert np.max(cv2.absdiff(restored, photo)) <= 5
    assert stamp.reverse(restored) is None
