from io import BytesIO
from pathlib import Path
from urllib.error import URLError

import cv2
import numpy as np
from PIL import Image

from conftest import cheap_fill
from synth import make_mark, stamp
from wmremove import batch
from wmremove.overlays import load_overlays
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
