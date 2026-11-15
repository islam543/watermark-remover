"""Process a folder, local image, or HTTP(S) link without moving the source."""
from __future__ import annotations

import io
import json
import logging
import os
import re
import shutil
import tempfile
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

import cv2
from PIL import Image, UnidentifiedImageError

from .pipeline import _free, clean_image
from .showrooms import showroom_listings, showroom_route

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
        domain = (urlsplit(page).hostname or "").removeprefix("www.")
        sources = (self.photos, self.products)
        if domain not in {"qatarsale.com", "mzadqatar.com", "qatarliving.com"}:
            sources += (self.previews,)
        for candidates in sources:
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


def _read_gallery_photo(url):
    parsed = urlsplit(url)
    if parsed.hostname == "qlv-media-prod.qatarliving.com" and parsed.path.startswith("/ad-images-output/"):
        # The listing metadata often advertises a missing original. Use the
        # same large WebP that the listing displays when you open the gallery.
        photo = PurePosixPath(unquote(parsed.path))
        directory = photo.parent
        stem = photo.stem
        if directory.name == "thumbnail":
            stem = re.sub(r"_\d+x\d+$", "", stem)
            directory = directory.parent
        gallery_path = quote(str(directory / "thumbnail" / f"{stem}_900x675.webp"))
        gallery_url = urlunsplit(parsed._replace(path=gallery_path, query="", fragment=""))
        if gallery_url != url:
            try:
                return _read_url(gallery_url)
            except HTTPError as exc:
                if exc.code not in (403, 404, 410):
                    raise
    return _read_url(url)


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


def _save_download(source, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest.parent) as staging:
        staged = Path(staging) / dest.name
        shutil.copyfile(source, staged)
        os.link(staged, dest)
    log.info("Saved %s", dest)
    return True


def _run_gallery(links, work, output, save):
    count = 0
    for url in links:
        try:
            final, _, data = _read_gallery_photo(url)
            src = _stage_image(final, data, work)
            count += save(src, _free(output / src.name))
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            log.error("Could not load %s: %s", url, exc)
            continue
    return count, len(links)


def _gallery_links(url, data):
    gallery = _Gallery()
    gallery.feed(data.decode("utf-8", errors="replace"))
    links = gallery.urls(url)
    if not links:
        raise ValueError("no gallery photos found; paste a car listing, a showroom, or a direct image link")
    return links


def _run_showroom(route, output, save, download_only):
    listings = {}
    inventory_complete = True
    try:
        listings.update(showroom_listings(route, lambda url: _read_url(url)[2]))
    except (OSError, ValueError) as exc:
        log.error("Could not finish reading the showroom inventory: %s", exc)
        inventory_complete = False
    if not listings:
        if inventory_complete:
            log.info("No car listings found in the showroom")
        return 1

    folder = "showroom-photos" if download_only else "showroom-clean"
    dest = output or _free(Path.cwd() / folder)
    dest.mkdir(parents=True, exist_ok=output is not None)
    log.info("Found %d car listings. Saving photos in %s", len(listings), dest.resolve())
    done = total = cars_done = 0
    for index, (listing_id, link) in enumerate(listings.items(), 1):
        log.info("Car %d of %d: %s", index, len(listings), link)
        try:
            url, content_type, data = _read_url(link)
            if content_type not in {"text/html", "application/xhtml+xml"}:
                raise ValueError("the listing did not return an HTML page")
            links = _gallery_links(url, data)
            with tempfile.TemporaryDirectory(prefix="wmremove-") as tmp:
                saved, expected = _run_gallery(links, Path(tmp), dest / listing_id, save)
            done += saved
            total += expected
            cars_done += saved == expected
        except (OSError, ValueError) as exc:
            log.error("Could not read car %s: %s", listing_id, exc)

    log.info("%s %d of %d photos found. Completed %d of %d discovered car galleries.",
             "Downloaded" if download_only else "Cleaned", done, total, cars_done, len(listings))
    return 0 if inventory_complete and cars_done == len(listings) else 1


def run_batch(source, output, cfg, target, inpaint, *, download_only=False):
    def save(src, dest):
        if download_only:
            return _save_download(src, dest)
        return _run_image(src, dest, cfg, target, inpaint)

    if _is_link(source):
        if route := showroom_route(source):
            return _run_showroom(route, output, save, download_only)
        url, content_type, data = _read_url(source)
        with tempfile.TemporaryDirectory(prefix="wmremove-") as tmp:
            work = Path(tmp)
            try:
                src = _stage_image(url, data, work)
            except UnidentifiedImageError:
                if content_type not in {"text/html", "application/xhtml+xml"}:
                    raise
                links = _gallery_links(url, data)
                folder = "listing-photos" if download_only else "listing-clean"
                dest = output or _free(Path.cwd() / folder)
                dest.mkdir(parents=True, exist_ok=output is not None)
                done, total = _run_gallery(links, work, dest, save)
            else:
                name = src.name if download_only else f"{src.stem}-clean{src.suffix}"
                dest = output or _free(Path.cwd() / name)
                done, total = save(src, dest), 1
    else:
        if download_only:
            raise ValueError("--download-only requires an HTTP(S) link")
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
    log.info("%s %d of %d %s", "Downloaded" if download_only else "Cleaned",
             done, total, "image" if total == 1 else "images")
    return 0 if done == total else 1
