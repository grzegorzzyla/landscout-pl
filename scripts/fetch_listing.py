"""
fetch_listing.py — pobierz POJEDYNCZE ogłoszenie z wklejonego URL i zwróć
znormalizowany rekord (taki sam schemat jak scrapery). Do trybu hybrydowego:
użytkownik wkleja link, my budujemy rekord, properties-list-manage go zapisuje.

Obsługa:
- olx.pl     → window.__PRERENDERED_STATE__ → ad (zawiera lat/lon, params, zdjęcia)
- otodom.pl  → <script id="__NEXT_DATA__"> → props.pageProps.ad (realne współrzędne)
- gethome.pl → window.__INITIAL_STATE__ → obiekt oferty

Użycie:
  python fetch_listing.py --url "https://www.otodom.pl/pl/oferta/...."
Wynik: JSON {"meta":..., "listings":[<record>]} (lista 0/1-elementowa) na stdout.
"""
from __future__ import annotations

import argparse
import base64
import json
import re

import common
import scrape_gethome
import scrape_olx
import scrape_otodom


def _infer_transaction(url: str) -> str:
    return "rent" if re.search(r"wynajem|do-wynajecia|wynajmij", url) else "sale"


def _downscale_olx(url: str) -> str:
    return re.sub(r";s=\d+x\d+", ";s=1024x768", url or "")


def _find_key(obj, key):
    if isinstance(obj, dict):
        if key in obj and isinstance(obj[key], dict):
            return obj[key]
        for v in obj.values():
            r = _find_key(v, key)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_key(v, key)
            if r:
                return r
    return None


# --- OLX ------------------------------------------------------------------
def fetch_olx(url: str, transaction: str) -> dict | None:
    html = common.http_get(url, accept="text/html").text
    m = re.search(r"window\.__PRERENDERED_STATE__\s*=\s*", html)
    if not m:
        return None
    qpos = html.index('"', m.end())
    inner, _ = json.JSONDecoder().raw_decode(html, qpos)
    state = json.loads(inner)
    container = _find_key(state, "ad") or {}
    ad = container.get("ad") if isinstance(container.get("ad"), dict) else container
    if not ad or not ad.get("id"):
        return None

    params = {p.get("key"): p.get("value") for p in ad.get("params", []) or []}
    loc = ad.get("location") or {}
    mp = ad.get("map") or {}
    price = common.to_int(((ad.get("price") or {}).get("regularPrice") or {}).get("value"))
    # dom rozpoznajemy po obecności 'builttype' (działka go nie ma); wtedy 'm'=pow. domu, 'area'=pow. działki
    is_dom = bool(params.get("builttype"))
    house_m2 = common.to_int(params.get("m"))
    if is_dom:
        area = common.to_int(params.get("area"))  # teren
    else:
        area = house_m2
    ppm = common.to_int(params.get("price_per_m"))
    if ppm is None and price and area and not is_dom:
        ppm = round(price / area)

    rec = common.empty_record()
    rec["source"] = "olx"
    rec["source_id"] = str(ad.get("id"))
    rec["url"] = ad.get("url") or url
    rec["title"] = ad.get("title")
    rec["kind"] = "dom" if is_dom else "dzialka"
    rec["price"] = price
    rec["area_m2"] = area
    rec["price_per_m2"] = None if is_dom else ppm
    rec["transaction"] = transaction
    if is_dom:
        rec["plot_type"] = params.get("builttype") if isinstance(params.get("builttype"), str) else None
        rec["raw"] = {"house_area_m2": house_m2, "house_price_per_m2": ppm}
    else:
        rec["plot_type"] = params.get("type") if isinstance(params.get("type"), str) else None
    rec["location"] = {
        "city": loc.get("cityName"),
        "region": loc.get("regionName"),
        "address": loc.get("districtName"),
    }
    if mp.get("lat") and mp.get("lon"):
        rec["lat"], rec["lon"] = mp["lat"], mp["lon"]
        rec["coords_approx"] = not mp.get("show_detailed", False)
    rec["owner_type"] = "agency" if ad.get("isBusiness") else "private"
    rec["images"] = [_downscale_olx(p if isinstance(p, str) else p.get("link", "")) for p in ad.get("photos", []) or []]
    rec["images"] = [i for i in rec["images"] if i]
    rec["date_created"] = ad.get("createdTime")
    rec["description"] = ad.get("description")
    return rec


# --- Otodom ---------------------------------------------------------------
def _otodom_city(loc: dict) -> str | None:
    rg = (loc.get("reverseGeocoding") or {}).get("locations") or []
    for level in ("city", "town", "village"):
        for node in rg:
            if node.get("locationLevel") == level:
                return node.get("name")
    return rg[-1]["name"] if rg else None


def fetch_otodom(url: str, transaction: str) -> dict | None:
    html = common.http_get(url, accept="text/html").text
    m = re.search(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        from scrape_otodom import _fetch_page_playwright  # fallback
        rendered = _fetch_page_playwright(url)
        if not rendered:
            return None
        m = re.search(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', rendered, re.S)
        if not m:
            return None
    ad = json.loads(m.group(1)).get("props", {}).get("pageProps", {}).get("ad")
    if not ad:
        return None
    target = ad.get("target") or {}
    loc = ad.get("location") or {}
    coords = loc.get("coordinates") or {}
    addr = loc.get("address") or {}

    # dom rozpoznajemy po obecności pola Terrain_area (działka go nie ma); wtedy Area=pow. domu, Terrain_area=teren
    terrain = common.to_int(target.get("Terrain_area"))
    house_m2 = common.to_int(target.get("Area"))
    is_dom = terrain is not None
    house_ppm = common.to_int(target.get("Price_per_m"))

    rec = common.empty_record()
    rec["source"] = "otodom"
    rec["source_id"] = str(ad.get("id"))
    rec["url"] = ad.get("url") or url
    rec["title"] = ad.get("title")
    rec["kind"] = "dom" if is_dom else "dzialka"
    rec["price"] = common.to_int(target.get("Price"))
    rec["area_m2"] = terrain if is_dom else house_m2
    rec["price_per_m2"] = None if is_dom else house_ppm
    rec["transaction"] = transaction
    build_type = (target.get("Build_type") or target.get("Building_type"))
    if isinstance(build_type, list):
        build_type = build_type[0] if build_type else None
    plot = build_type or next(
        (c.get("value") for c in ad.get("characteristics", []) if c.get("key") == "type"), None)
    rec["plot_type"] = plot
    if is_dom:
        rec["raw"] = {"terrain_area_m2": terrain, "house_area_m2": house_m2, "house_price_per_m2": house_ppm}
    rec["location"] = {
        "city": _otodom_city(loc),
        "region": next((c.get("value") for c in ad.get("characteristics", []) if c.get("key") == "province"), None),
        "address": (addr.get("street") or {}).get("name") if addr.get("street") else None,
    }
    if coords.get("latitude") and coords.get("longitude"):
        rec["lat"], rec["lon"] = coords["latitude"], coords["longitude"]
        rec["coords_approx"] = False
    atype = (ad.get("advertiserType") or "").lower()
    rec["owner_type"] = "private" if atype == "private" else ("developer" if atype == "developer" else "agency")
    rec["images"] = [img.get("large") for img in ad.get("images", []) or [] if img.get("large")]
    rec["date_created"] = ad.get("createdAt")
    rec["description"] = re.sub(r"<[^>]+>", " ", ad.get("description") or "").strip() or None
    return rec


# --- gethome --------------------------------------------------------------
def fetch_gethome(url: str, transaction: str) -> dict | None:
    html = common.http_get(url, accept="text/html").text
    state = scrape_gethome._extract_initial_state(html)
    if not state:
        return None

    def find_offer(obj):
        if isinstance(obj, dict):
            if obj.get("coordinates") and obj.get("price") and (obj.get("property") or obj.get("name")):
                return obj
            for v in obj.values():
                r = find_offer(v)
                if r:
                    return r
        elif isinstance(obj, list):
            for v in obj:
                r = find_offer(v)
                if r:
                    return r
        return None

    offer = find_offer(state)
    if not offer:
        return None
    prop = offer.get("property") or {}
    # dom: property.type == "house" lub obecny lot_size (pow. działki obok pow. domu)
    kind = "dom" if (prop.get("type") == "house" or prop.get("lot_size")) else "dzialka"
    return scrape_gethome.normalize(offer, transaction, kind)


# --- Morizon -------------------------------------------------------------
def _morizon_ld_offer(html: str) -> dict:
    """Znajdź blok JSON-LD @type=Offer (z ceną) na karcie morizon."""
    found: dict = {}

    def walk(o):
        nonlocal found
        if found:
            return
        if isinstance(o, dict):
            if o.get("@type") == "Offer" and o.get("price") is not None:
                found = o
                return
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        try:
            walk(json.loads(m.group(1)))
        except Exception:
            continue
        if found:
            break
    return found


def fetch_morizon(url: str, transaction: str) -> dict | None:
    html = common.http_get(url, accept="text/html").text
    offer = _morizon_ld_offer(html)
    if not offer:
        return None
    name = offer.get("name") or ""
    cat = (offer.get("category") or "").lower()
    is_dom = ("dom" in cat) or bool(re.search(r"/oferta/sprzedaz-dom-", url))
    am = re.search(r"-(\d+)m2-mzn", url) or re.search(r"([\d\s]+)\s*m²", name)
    area = common.to_int(am.group(1)) if am else None
    loc_m = re.search(r"m²\s+(.+?)\s*$", name)
    mid = re.search(r"(mzn\d+)", url)
    # Galeria: miniatury morizon kodują w base64 URL oryginału (cdngr.pl) — odtwórz pełne zdjęcia.
    images, seen = [], set()
    for b in re.findall(r"/thumb/([A-Za-z0-9=]+)/", html):
        try:
            orig = base64.b64decode(b + "=" * (-len(b) % 4)).decode("utf-8", "ignore")
        except Exception:
            continue
        if orig.startswith("http") and re.search(r"\.(jpe?g|png|webp)", orig, re.I) and orig not in seen:
            seen.add(orig)
            images.append(orig)
    if not images:  # fallback: pojedyncze zdjęcie z JSON-LD
        img = offer.get("image")
        images = [img] if isinstance(img, str) and img else ([u for u in img if isinstance(u, str)] if isinstance(img, list) else [])

    rec = common.empty_record()
    rec["source"] = "morizon"
    rec["source_id"] = mid.group(1) if mid else url
    rec["url"] = offer.get("url") or url
    rec["title"] = name or None
    rec["kind"] = "dom" if is_dom else "dzialka"
    rec["price"] = common.to_int(offer.get("price"))
    rec["transaction"] = transaction
    rec["location"] = {"city": (loc_m.group(1).strip() if loc_m else None), "region": None, "address": None}
    if is_dom:
        rec["area_m2"] = None
        rec["raw"] = {"house_area_m2": area}
    else:
        rec["area_m2"] = area
        rec["price_per_m2"] = (rec["price"] // area) if (rec["price"] and area) else None
    rec["images"] = images
    rec["description"] = re.sub(r"<[^>]+>", " ", offer.get("description") or "").strip() or None
    return rec


# --- adresowo.pl ----------------------------------------------------------
def fetch_adresowo(url: str, transaction: str) -> dict | None:
    """Karta oferty adresowo.pl — dane siedzą w JSON-LD (@graph):
    Place{address.streetAddress, geo{latitude,longitude}, name, description} + Offer{price}.
    W przeciwieństwie do listy, karta podaje REALNE współrzędne (nie centroid miejscowości).
    """
    import scrape_adresowo as A
    html = A._fetch(url)                      # normalizuje encje (&nbsp;) — patrz scrape_adresowo
    place, offer = {}, {}
    for m in re.finditer(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S):
        try:
            data = json.loads(m.group(1))
        except Exception:  # noqa: BLE001
            continue
        for node in (data.get("@graph") or [data]):
            t = node.get("@type")
            if t == "Place":
                place = node
            elif t == "Offer":
                offer = node
    if not place and not offer:
        return None

    rec = common.empty_record()
    rec["source"] = "adresowo"
    m = re.search(r"/o/([a-z0-9-]+)$", url)
    rec["source_id"] = m.group(1).rsplit("-", 1)[-1] if m else url.rsplit("/", 1)[-1]
    rec["url"] = url
    rec["title"] = place.get("name") or None
    rec["transaction"] = transaction
    try:
        rec["price"] = int(float(offer.get("price"))) if offer.get("price") else None
    except (TypeError, ValueError):
        rec["price"] = None

    # powierzchnia: z nazwy ("… - 2,02 ha") albo z treści strony
    area = None
    for src in (place.get("name") or "", html):
        mm = re.search(r"([\d]+(?:[.,][\d]+)?)\s*ha\b", src)
        if mm:
            area = int(round(float(mm.group(1).replace(",", ".")) * 10000))
            break
        mm = re.search(r"([\d\s]{3,9})\s*m²", src)
        if mm:
            try:
                area = int(re.sub(r"\s", "", mm.group(1)))
            except ValueError:
                area = None
            break
    rec["area_m2"] = area
    if rec["price"] and rec["area_m2"]:
        rec["price_per_m2"] = round(rec["price"] / rec["area_m2"])

    geo = place.get("geo") or {}
    try:
        rec["lat"] = float(geo["latitude"]); rec["lon"] = float(geo["longitude"])
        rec["coords_approx"] = False        # karta podaje realną pozycję działki
    except (KeyError, TypeError, ValueError):
        rec["coords_approx"] = True

    addr = ((place.get("address") or {}).get("streetAddress") or "")
    parts = [x.strip() for x in addr.split(",") if x.strip()]
    rec["location"] = {"city": parts[0] if parts else None,
                       "region": parts[-1] if len(parts) > 1 else None,
                       "address": addr or None}
    mt = re.search(r"Działka\s+([a-ząćęłńóśźż-]+)", place.get("name") or "", re.I)
    rec["plot_type"] = mt.group(1).lower() if mt else None
    rec["description"] = place.get("description") or None
    rec["owner_type"] = "private"
    rec["images"] = sorted(set(re.findall(r'https://s\d\.adresowa\.pl/[^"\s]+\.webp', html)))[:40]
    rec["raw"] = {"street_address": addr or None}
    return rec


PORTALS = {
    "olx.pl": fetch_olx,
    "otodom.pl": fetch_otodom,

    "gethome.pl": fetch_gethome,
    "morizon.pl": fetch_morizon,
    "adresowo.pl": fetch_adresowo,
}


def fetch(url: str) -> tuple[list[dict], dict]:
    transaction = _infer_transaction(url)
    meta = {"url": url, "transaction": transaction}
    handler = next((fn for dom, fn in PORTALS.items() if dom in url), None)
    if handler is None:
        meta["error"] = f"Nieobsługiwany portal: {url}"
        return [], meta
    meta["source"] = handler.__name__.replace("fetch_", "")
    try:
        rec = handler(url, transaction)
    except Exception as exc:  # noqa: BLE001
        meta["error"] = f"Błąd pobierania: {exc}"
        return [], meta
    if not rec:
        meta["error"] = "Nie udało się wyciągnąć danych ze strony (zmiana struktury lub blokada)."
        return [], meta
    return [rec], meta


def main(argv: list[str] | None = None) -> int:
    common.setup_utf8()
    p = argparse.ArgumentParser(description="Pobierz pojedyncze ogłoszenie z URL.")
    p.add_argument("--url", required=True)
    args = p.parse_args(argv)
    records, meta = fetch(args.url)
    meta["returned"] = len(records)
    common.emit(records, meta)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
