"""Discover car listings in the public inventory of a supported showroom."""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from urllib.parse import quote, unquote, urlencode, urlsplit


ROUTES = {
    "qatarsale.com": r"(?P<lang>/ar|/en)?/showroom/(?P<key>[^/]+)(?:/[^/]+)?",
    "mzadqatar.com": r"(?P<lang>/ar|/en)?/user/(?P<key>[0-9]+)",
    "qatarliving.com": r"(?P<lang>/ar|/en)?/vehicles/showrooms/(?P<key>[^/]+-[0-9]+)(?:/[^/]+)?",
}
QL_API = "https://bo-prod.qatarliving.com"


def showroom_route(url):
    parsed = urlsplit(url)
    domain = (parsed.hostname or "").removeprefix("www.")
    pattern = ROUTES.get(domain)
    match = re.fullmatch(pattern, parsed.path.rstrip("/")) if pattern else None
    return (domain, match["lang"] or "/en", match["key"]) if match else None


class _InventoryData(HTMLParser):
    def __init__(self, data):
        super().__init__()
        self.inertia = None
        self.angular = None
        self._state = None
        self.feed(data.decode("utf-8", errors="replace"))

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("data-page") and self.inertia is None:
            self.inertia = attrs["data-page"]
        if tag == "script" and attrs.get("id") == "serverApp-state":
            self._state = []

    def handle_data(self, data):
        if self._state is not None:
            self._state.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._state is not None:
            escapes = {"q": '"', "a": "&", "s": "'", "l": "<", "g": ">"}
            self.angular = re.sub(r"&([qaslg]);", lambda match: escapes[match[1]], "".join(self._state))
            self._state = None


def _qatarsale(lang, key, fetch):
    base = f"https://qatarsale.com{lang}/showroom/{key}/cars_for_sale"
    page = 1
    products_seen = set()
    while True:
        state = _InventoryData(fetch(f"{base}?page={page}")).angular
        inventory = json.loads(state)["ProductList"]
        if inventory["currentPage"] != page - 1:
            raise ValueError(f"QatarSale returned the wrong inventory page for page {page}")
        items = inventory["list"]
        if not items and inventory["totalCount"]:
            raise ValueError(f"QatarSale returned an empty inventory page for page {page}")
        for item in items:
            listing_id = str(item["id"])
            if listing_id not in products_seen and item["showroomUri"] == unquote(key) and item["categoryUri"] == "cars_for_sale":
                slug = quote(item["uri"], safe="%")
                yield listing_id, f"https://qatarsale.com{lang}/product/{slug}"
            products_seen.add(listing_id)
        if page >= inventory["pagesCount"]:
            if len(products_seen) < inventory["totalCount"]:
                raise ValueError("QatarSale returned fewer listings than its inventory count")
            return
        page += 1


def _mzad(lang, key, fetch):
    base = f"https://mzadqatar.com{lang}/user/{key}"
    page = 1
    products_seen = set()
    while True:
        state = _InventoryData(fetch(base if page == 1 else f"{base}?page={page}")).inertia
        profile = json.loads(state)["props"]["getCompanySellerProfile"]
        if int(profile["currentPage"]) != page:
            raise ValueError(f"Mzad Qatar returned the wrong inventory page for page {page}")
        items = profile["products"]
        new_ids = {str(item["productId"]) for item in items} - products_seen
        for item in items:
            listing_id = str(item["productId"])
            if listing_id in new_ids and str(item["categoryId"]) == "1":
                path = item["productUrlWeb"]
                if not re.fullmatch(rf"/products/[^/]+-{re.escape(listing_id)}", path):
                    raise ValueError(f"Mzad Qatar returned an invalid link for car {listing_id}")
                yield listing_id, f"https://mzadqatar.com{lang}{quote(path, safe='/%')}"
        products_seen.update(new_ids)
        if len(products_seen) >= profile["userNumberOfAdsDecimal"]:
            return
        if not new_ids:
            raise ValueError(f"Mzad Qatar inventory stopped before all ads were found on page {page}")
        page += 1


def _qatarliving(lang, key, fetch):
    dealer = json.loads(fetch(f"{QL_API}/showrooms/{key}"))
    agency = int(dealer["agencyId"])
    page = 1
    ads_seen = set()
    while True:
        query = urlencode({"agencyIds": agency, "cur_page": page, "per_page": 20})
        inventory = json.loads(fetch(f"{QL_API}/showroom-ads?{query}"))
        meta, items = inventory["meta"], inventory["adsCar"]
        if meta["curPage"] != page or (not items and meta["totalResults"]):
            raise ValueError(f"Qatar Living returned an incomplete inventory page for page {page}")
        for item in items:
            listing_id = str(item["adId"])
            if listing_id not in ads_seen and item["categoryId"] == 1:
                path = item["urls"][0]["urlAlias"]
                if not re.fullmatch(rf"/vehicles/cars/{re.escape(listing_id)}_[^/]+", path):
                    raise ValueError(f"Qatar Living returned an invalid link for car {listing_id}")
                yield listing_id, f"https://www.qatarliving.com{lang}{quote(path, safe='/%')}"
            ads_seen.add(listing_id)
        if page >= meta["totalPages"]:
            if len(ads_seen) < meta["totalResults"]:
                raise ValueError("Qatar Living returned fewer ads than its inventory count")
            return
        page += 1


def showroom_listings(route, fetch):
    domain, lang, key = route
    read = {
        "qatarsale.com": _qatarsale,
        "mzadqatar.com": _mzad,
        "qatarliving.com": _qatarliving,
    }[domain]
    try:
        for listing_id, url in read(lang, key, fetch):
            if not listing_id.isascii() or not listing_id.isdecimal():
                raise ValueError(f"{domain} returned an invalid listing ID")
            yield listing_id, url
    except (AttributeError, IndexError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read the showroom inventory from {domain}") from exc
