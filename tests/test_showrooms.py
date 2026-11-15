import html
import json
from io import BytesIO

import pytest
from PIL import Image

from wmremove import batch
from wmremove.showrooms import QL_API


def _qatar_sale_page(page, listing_id):
    record = {
        "id": listing_id, "uri": f"car-{listing_id}",
        "showroomUri": "dealer", "categoryUri": "cars_for_sale",
    }
    state = {"ProductList": {
        "currentPage": page - 1, "pagesCount": 2, "totalCount": 2, "list": [record],
    }}
    payload = json.dumps(state).replace('"', "&q;")
    return f'<script id="serverApp-state" type="application/json">{payload}</script>'.encode()


def _mzad_page(page, listing_id):
    record = {"productId": listing_id, "productUrlWeb": f"/products/سيارة-{listing_id}", "categoryId": "1"}
    accessory = {"productId": 999, "productUrlWeb": "/products/accessory-999", "categoryId": "2"}
    state = {"props": {"getCompanySellerProfile": {
        "currentPage": str(page), "userNumberOfAdsDecimal": 3,
        "products": [record, accessory] if page == 1 else [record],
    }}}
    return f'<div data-page="{html.escape(json.dumps(state), quote=True)}"></div>'.encode()


def _qatar_living_page(page, listing_id):
    return json.dumps({
        "meta": {"curPage": page, "totalPages": 2, "totalResults": 2},
        "adsCar": [{"adId": listing_id, "categoryId": 1,
                    "urls": [{"urlAlias": f"/vehicles/cars/{listing_id}_car"}]}],
    }).encode()


@pytest.mark.parametrize("site", ["qatarsale", "mzad", "qatarliving"])
def test_showroom_processes_every_page_and_separates_cars(tmp_path, monkeypatch, site):
    if site == "qatarsale":
        home = "https://qatarsale.com/en/showroom/dealer"
        inventories = {f"{home}/cars_for_sale?page={p}": _qatar_sale_page(p, 100 + p) for p in (1, 2)}
        listing = "https://qatarsale.com/en/product/car-{}"
    elif site == "mzad":
        home = "https://mzadqatar.com/en/user/1234"
        inventories = {home: _mzad_page(1, 101), f"{home}?page=2": _mzad_page(2, 102)}
        listing = "https://mzadqatar.com/en/products/%D8%B3%D9%8A%D8%A7%D8%B1%D8%A9-{}"
    else:
        home = "https://www.qatarliving.com/en/vehicles/showrooms/dealer-12/toyota"
        inventories = {f"{QL_API}/showrooms/dealer-12": b'{"agencyId": 12}'}
        inventories.update({
            f"{QL_API}/showroom-ads?agencyIds=12&cur_page={p}&per_page=20": _qatar_living_page(p, 100 + p)
            for p in (1, 2)
        })
        listing = "https://www.qatarliving.com/en/vehicles/cars/{}_car"

    photo = BytesIO()
    Image.new("RGB", (10, 10)).save(photo, format="PNG")
    sources = {}
    for ident in (101, 102):
        # Identical basenames in different galleries must get separate folders.
        image = f"https://photos.example/{ident}/front.png"
        metadata = json.dumps({"@type": "Car", "image": [image]})
        sources[listing.format(ident)] = f'<script type="application/ld+json">{metadata}</script>'.encode()
        sources[image] = photo.getvalue()

    def fetch(url):
        if url in inventories:
            return url, "text/html", inventories[url]
        if url.endswith(".png"):
            return url, "image/png", sources[url]
        return url, "text/html", sources[url]

    cleaned = []

    def clean(src, dest, cfg, target, inpaint):
        cleaned.append(dest)
        return batch._save_download(src, dest)

    monkeypatch.setattr(batch, "_read_url", fetch)
    monkeypatch.setattr(batch, "_run_image", clean)
    output = tmp_path / "results"
    download_only = site != "qatarliving"
    assert batch.run_batch(home + "?page=4", output, None, None, None,
                           download_only=download_only) == 0
    expected = {output / str(i) / "front.png" for i in (101, 102)}
    assert set(output.rglob("*.png")) == expected
    assert all(path.read_bytes() == photo.getvalue() for path in expected)
    assert set(cleaned) == (set() if download_only else expected)


def test_showroom_keeps_discovered_galleries_when_inventory_fails(tmp_path, monkeypatch, caplog):
    home = "https://qatarsale.com/en/showroom/dealer"
    photo = BytesIO()
    Image.new("RGB", (10, 10)).save(photo, format="PNG")

    def fetch(url):
        if url == f"{home}/cars_for_sale?page=1":
            return url, "text/html", _qatar_sale_page(1, 101)
        if url == f"{home}/cars_for_sale?page=2":
            raise OSError("page unavailable")
        if url.endswith("car-101"):
            return url, "text/html", b'<script type="application/ld+json">{"@type":"Car","image":"front.png"}</script>'
        if url.endswith("front.png"):
            return url, "image/png", photo.getvalue()
        pytest.fail(f"Unexpected URL: {url}")

    monkeypatch.setattr(batch, "_read_url", fetch)
    assert batch.run_batch(home, tmp_path, None, None, None, download_only=True) == 1
    assert "Could not finish reading the showroom inventory" in caplog.text
    assert (tmp_path / "101" / "front.png").read_bytes() == photo.getvalue()
