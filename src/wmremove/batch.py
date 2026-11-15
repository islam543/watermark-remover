"""Process a folder, local image, or HTTP(S) link without moving the source."""
from __future__ import annotations

import io
import json
import logging
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlsplit
from urllib.request import Request, urlopen

import cv2
from PIL import Image, UnidentifiedImageError

from .pipeline import _free, clean_image

log = logging.getLogger("wmremove")
EXTENSIONS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "TIFF": ".tiff"}
IMAGE_SUFFIXES = set(EXTENSIONS.values()) | {".jpeg", ".tif"}
MAX_DOWNLOAD = 50 * 1024 * 1024


def _download(request):
    with urlopen(request, timeout=20) as response:
        data = response.read(MAX_DOWNLOAD + 1)
        if len(data) > MAX_DOWNLOAD:
            raise ValueError("download exceeds 50 MB")
        return response.geturl(), response.headers.get_content_type(), data


def _read_url(url):
    if urlsplit(url).scheme not in {"http", "https"}:
        raise ValueError("image links must use HTTP or HTTPS")
    request = Request(url, headers={"User-Agent": "wmremove/0.1",
                                    "Accept": "image/*,text/html;q=0.9,*/*;q=0.1"})
    transient = (TimeoutError, ConnectionResetError)
    try:
        return _download(request)
    except HTTPError as exc:
        if exc.code not in (408, 502, 503, 504):
            raise
    except URLError as exc:
        if not isinstance(exc.reason, transient):
            raise
    except transient:
        pass
    return _download(request)


def _objects(value):
    if isinstance(value, list):
        for item in value:
            yield from _objects(item)
    elif isinstance(value, dict):
        yield value
        yield from _objects(value.get("@graph"))


class _Gallery(HTMLParser):
    def __init__(self):
        super().__init__()
        self.photos = []
        self.products = []
        self.previews = []
        self._schema = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("type") == "application/ld+json":
            self._schema = []
        if tag == "meta" and attrs.get("property") in {"og:image", "og:image:url"}:
            self.previews.append(attrs.get("content"))
        if "data-page" in attrs:
            try:
                page = json.loads(attrs["data-page"])
                photos = page["props"]["ads"]["productImages"]
            except (ValueError, TypeError, KeyError):
                return
            if isinstance(photos, list):
                self.photos.extend(photos)

    def handle_data(self, data):
        if self._schema is not None:
            self._schema.append(data)

    def handle_endtag(self, tag):
        if tag != "script" or self._schema is None:
            return
        payload, self._schema = "".join(self._schema), None
        try:
            schema = json.loads(payload)
        except ValueError:
            return
        for item in _objects(schema):
            types = item.get("@type")
            types = types if isinstance(types, list) else [types]
            if any(kind in ("Product", "Vehicle", "Car") for kind in types):
                images = item.get("image")
                for img in (images if isinstance(images, list) else [images]):
                    if isinstance(img, dict):
                        img = img.get("contentUrl") or img.get("url")
                    self.products.append(img)

    def urls(self, page):
        links = {}
        for candidates in (self.photos, self.products, self.previews):
            for item in candidates:
                if isinstance(item, str) and item.strip():
                    url = urljoin(page, item.strip())
                    if urlsplit(url).scheme in {"http", "https"}:
                        links[url] = None
            if links:
                return list(links)
        return []


def _stage_image(url, data, work):
    with Image.open(io.BytesIO(data)) as image:
        if image.format not in EXTENSIONS:
            raise ValueError(f"unsupported image format: {image.format}")
        suffix = EXTENSIONS[image.format]
    stem = Path(unquote(urlsplit(url).path)).stem
    name = stem if stem and not stem.startswith(".") else "image"
    path = _free(work / (name + suffix))
    path.write_bytes(data)
    return path


def _is_link(source):
    return urlsplit(source).scheme.lower() in {"http", "https"}


def _run_image(src, dest, cfg, target, inpaint):
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        status, reason, _, _ = clean_image(src, dest, cfg, target, inpaint, exclusive=True)
        if status == "clean":
            log.info("%s → %s", src.name, dest)
            return True
        log.warning("%s: %s", src.name, reason)
    except (OSError, ValueError, RuntimeError, cv2.error, Image.DecompressionBombError) as exc:
        log.error("%s: %s", src.name, exc)
    return False


def _run_gallery(links, work, output, cfg, target, inpaint):
    count = 0
    for url in links:
        try:
            final, _, data = _read_url(url)
            src = _stage_image(final, data, work)
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            log.error("Could not load %s: %s", url, exc)
            continue
        count += _run_image(src, _free(output / src.name), cfg, target, inpaint)
    return count, len(links)


def run_batch(source, output, cfg, target, inpaint):
    if _is_link(source):
        url, content_type, data = _read_url(source)
        with tempfile.TemporaryDirectory(prefix="wmremove-") as tmp:
            work = Path(tmp)
            try:
                src = _stage_image(url, data, work)
            except UnidentifiedImageError:
                if content_type not in {"text/html", "application/xhtml+xml"}:
                    raise
                gallery = _Gallery()
                gallery.feed(data.decode("utf-8", errors="replace"))
                links = gallery.urls(url)
                if not links:
                    raise ValueError("no gallery photos found in the page; use a direct image link")
                dest = output or _free(Path.cwd() / "listing-clean")
                dest.mkdir(parents=True, exist_ok=output is not None)
                done, total = _run_gallery(links, work, dest, cfg, target, inpaint)
            else:
                dest = output or _free(Path.cwd() / f"{src.stem}-clean{src.suffix}")
                done, total = _run_image(src, dest, cfg, target, inpaint), 1
    else:
        src = Path(source).expanduser().resolve(strict=True)
        if src.is_dir():
            dest = (output or _free(src.with_name(src.name + "-clean"))).resolve()
            if dest == src:
                raise ValueError("choose a different output folder")
            nested = dest.is_relative_to(src)
            paths = sorted(
                path for path in src.rglob("*")
                if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
                and not (nested and path.is_relative_to(dest))
            )
            if not paths:
                raise ValueError(f"no supported images found in {src}")
            dest.mkdir(parents=True, exist_ok=output is not None)
            done = sum(
                _run_image(path, _free(dest / path.relative_to(src)), cfg, target, inpaint)
                for path in paths
            )
            total = len(paths)
        else:
            dest = output or _free(src.with_name(f"{src.stem}-clean{src.suffix}"))
            done, total = _run_image(src, dest, cfg, target, inpaint), 1
    log.info("Cleaned %d of %d %s", done, total, "image" if total == 1 else "images")
    return 0 if done == total else 1
