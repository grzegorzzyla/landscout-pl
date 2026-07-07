"""
scrape_otodom.py — listowanie działek z Otodom przez parsowanie __NEXT_DATA__.

Mechanika (zweryfikowana empirycznie):
- resolver lokalizacji: Otodom wymaga ścieżki hierarchicznej
  region/powiat/gmina/miasto (np. dolnoslaskie/klodzki/klodzko/klodzko).
  Budujemy ją z Nominatim (OSM) i próbujemy od najbardziej szczegółowej.
- listing: GET /pl/wyniki/{sprzedaz|wynajem}/dzialka/{ścieżka}?distanceRadius=..&areaMin=..&page=..
  Dane są w <script id="__NEXT_DATA__"> → props.pageProps.data.searchAds.items.
- anti-bot: DataDome. Zwykły GET zwykle zwraca 200 z pełnymi danymi; przy 403/captcha
  uruchamiamy fallback Playwright (jeśli zainstalowany browser).

Otodom nie podaje współrzędnych w listingu — lat/lon zostają puste (uzupełniane
geokodowaniem dopiero przy dodaniu pozycji do listy).

Użycie:
  python scrape_otodom.py --location "Kłodzko" --distance 15 \
      --area-min 1000 --area-max 3500 --price-max 700000 --max 100
"""
from __future__ import annotations

import argparse
import json
import sys

from lxml import html as LH

import common

ALLOWED_RADIUS = [0, 5, 10, 15, 25, 50, 75]


def snap_radius(km: int) -> int:
    return min(ALLOWED_RADIUS, key=lambda x: abs(x - km))


def _strip_prefix(value: str | None, *prefixes: str) -> str | None:
    if not value:
        return None
    out = value
    for pref in prefixes:
        if out.lower().startswith(pref):
            out = out[len(pref):]
    return out.strip()


def location_path_candidates(name: str) -> list[str]:
    """Z Nominatim zbuduj kandydatów ścieżki Otodom, od najbardziej szczegółowej."""
    res = common.osm_lookup(name)
    if not res:
        return []
    addr = res.get("address", {})
    region = common.slugify(_strip_prefix(addr.get("state"), "województwo ") or "")
    county = common.slugify(_strip_prefix(addr.get("county"), "powiat ") or "")
    gmina = common.slugify(_strip_prefix(addr.get("municipality"), "gmina ") or "")
    place = addr.get("city") or addr.get("town") or addr.get("village")
    place_slug = common.slugify(place) if place else ""

    cands: list[str] = []
    if region and county and gmina and place_slug:
        cands.append(f"{region}/{county}/{gmina}/{place_slug}")
    if region and county and gmina:
        cands.append(f"{region}/{county}/{gmina}")
    if region and place_slug:
        cands.append(f"{region}/{place_slug}")
    if region:
        cands.append(region)
    # usuń duplikaty zachowując kolejność
    seen: set[str] = set()
    return [c for c in cands if not (c in seen or seen.add(c))]


def _extract_next_data(html_text: str) -> dict | None:
    try:
        doc = LH.fromstring(html_text)
        node = doc.xpath('//script[@id="__NEXT_DATA__"]/text()')
        if not node:
            return None
        return json.loads(node[0])
    except Exception:
        return None


def _fetch_page_playwright(url: str) -> str | None:
    """Fallback na DataDome: renderuj stronę headless i zwróć HTML."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        sys.stderr.write("[otodom] Playwright niedostępny — pomijam fallback.\n")
        return None
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_context(
                user_agent=common.UA, locale="pl-PL"
            ).new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_selector('script#__NEXT_DATA__', timeout=15000)
            content = page.content()
            browser.close()
            return content
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"[otodom] Fallback Playwright nieudany: {exc}\n")
        return None


def _agency_owner_type(item: dict) -> str:
    if item.get("isPrivateOwner"):
        return "private"
    agency = item.get("agency") or {}
    atype = (agency.get("type") or "").upper()
    if atype == "DEVELOPER":
        return "developer"
    return "agency"


def normalize(item: dict, transaction: str, kind: str = "dzialka") -> dict:
    rec = common.empty_record()
    loc = item.get("location") or {}
    addr = loc.get("address") or {}
    total_price = item.get("totalPrice") or {}
    ppm = item.get("pricePerSquareMeter") or {}
    terrain = common.to_int(item.get("terrainAreaInSquareMeters"))
    house = common.to_int(item.get("areaInSquareMeters"))

    rec["source"] = "otodom"
    rec["source_id"] = str(item.get("id"))
    # href z listingu bywa szablonem względnym ("[lang]/ad/<slug>") — buduj z slug do /pl/oferta/<slug>
    slug = item.get("slug")
    href = item.get("href")
    if slug:
        rec["url"] = f"https://www.otodom.pl/pl/oferta/{slug}"
    elif href:
        h = href.replace("[lang]", "pl")
        rec["url"] = h if h.startswith("http") else "https://www.otodom.pl/" + h.lstrip("/")
    else:
        rec["url"] = None
    rec["title"] = item.get("title")
    rec["kind"] = kind
    rec["price"] = common.to_int(total_price.get("value"))
    rec["transaction"] = transaction
    rec["plot_type"] = None  # Otodom nie wystawia rodzaju na listingu
    if kind == "dom":
        # dom: area_m2 = powierzchnia działki (teren); pow. domu i zł/m² (domu) -> raw
        rec["area_m2"] = terrain
        rec["price_per_m2"] = None
    else:
        rec["area_m2"] = house  # dla działki areaInSquareMeters to pow. działki
        rec["price_per_m2"] = common.to_int(ppm.get("value"))
    street = (addr.get("street") or {}).get("name") if addr.get("street") else None
    rec["location"] = {
        "city": (addr.get("city") or {}).get("name"),
        "region": (addr.get("province") or {}).get("name"),
        "address": street,
    }
    # Brak współrzędnych na listingu Otodom -> uzupełniane później
    rec["lat"] = None
    rec["lon"] = None
    rec["coords_approx"] = True
    rec["owner_type"] = _agency_owner_type(item)
    rec["images"] = [img.get("large") for img in (item.get("images") or []) if img.get("large")]
    rec["date_created"] = item.get("dateCreated")
    rec["description"] = item.get("shortDescription")
    rec["raw"] = {"terrain_area_m2": terrain}
    if kind == "dom":
        rec["raw"]["house_area_m2"] = house
        rec["raw"]["house_price_per_m2"] = common.to_int(ppm.get("value"))
    return rec


def _fetch_page_html(url: str) -> tuple[str, dict | None]:
    resp = common.http_get(url, accept="text/html")
    nd = _extract_next_data(resp.text) if resp.status_code == 200 else None
    if nd is None:
        # DataDome/captcha lub błąd -> fallback Playwright
        html_text = _fetch_page_playwright(url)
        if html_text:
            nd = _extract_next_data(html_text)
    return url, nd


def scrape(args) -> tuple[list[dict], dict]:
    seg = "sprzedaz" if args.transaction == "sale" else "wynajem"
    kind_seg = "dom" if args.kind == "dom" else "dzialka"
    radius = snap_radius(args.distance)
    candidates = location_path_candidates(args.location)
    meta = {
        "source": "otodom",
        "location": args.location,
        "kind": args.kind,
        "transaction": args.transaction,
        "distance_radius": radius,
    }
    if not candidates:
        meta["error"] = f"Nie udało się zbudować ścieżki Otodom dla '{args.location}'."
        return [], meta

    base_query = {"distanceRadius": radius, "limit": 36}
    # dom: filtr powierzchni dotyczy DZIAŁKI (terrainArea*), bo areaMin filtruje pow. domu
    area_min_key = "terrainAreaMin" if args.kind == "dom" else "areaMin"
    area_max_key = "terrainAreaMax" if args.kind == "dom" else "areaMax"
    if args.area_min is not None:
        base_query[area_min_key] = args.area_min
    if args.area_max is not None:
        base_query[area_max_key] = args.area_max
    if args.price_min is not None:
        base_query["priceMin"] = args.price_min
    if args.price_max is not None:
        base_query["priceMax"] = args.price_max

    # wybierz pierwszą ścieżkę, która zwraca dane
    chosen_path = None
    first_nd = None
    for path in candidates:
        url = f"https://www.otodom.pl/pl/wyniki/{seg}/{kind_seg}/{path}"
        q = "&".join(f"{k}={v}" for k, v in base_query.items())
        _, nd = _fetch_page_html(f"{url}?{q}&page=1")
        if nd:
            sa = nd.get("props", {}).get("pageProps", {}).get("data", {}).get("searchAds")
            if sa and sa.get("items"):
                chosen_path = path
                first_nd = nd
                break
    if not chosen_path:
        meta["error"] = "Brak wyników lub blokada (DataDome) dla wszystkich kandydatów ścieżki."
        meta["candidates"] = candidates
        return [], meta

    meta["path"] = chosen_path
    records: list[dict] = []

    def collect(nd: dict) -> dict:
        sa = nd["props"]["pageProps"]["data"]["searchAds"]
        for it in sa.get("items", []) or []:
            records.append(normalize(it, args.transaction, args.kind))
        return sa.get("pagination", {}) or {}

    pagination = collect(first_nd)
    total_pages = pagination.get("totalPages", 1)
    total_items = pagination.get("totalItems")
    url_base = f"https://www.otodom.pl/pl/wyniki/{seg}/{kind_seg}/{chosen_path}"
    q = "&".join(f"{k}={v}" for k, v in base_query.items())
    page = 2
    while len(records) < args.max and page <= total_pages:
        _, nd = _fetch_page_html(f"{url_base}?{q}&page={page}")
        if not nd:
            break
        collect(nd)
        page += 1

    records = common.dedupe(records)[: args.max]
    meta["total_available"] = total_items
    meta["returned"] = len(records)
    return records, meta


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Listowanie działek z Otodom (__NEXT_DATA__).")
    p.add_argument("--location", required=True, help="Miejscowość, np. 'Kłodzko'")
    p.add_argument("--kind", choices=["dzialka", "dom"], default="dzialka",
                   help="Typ nieruchomości: dzialka (domyślnie) lub dom (obejmuje siedliska/gospodarstwa)")
    p.add_argument("--distance", type=int, default=15, help="Promień w km (snap do 0/5/10/15/25/50/75)")
    p.add_argument("--area-min", type=int, default=None, dest="area_min")
    p.add_argument("--area-max", type=int, default=None, dest="area_max")
    p.add_argument("--price-min", type=int, default=None, dest="price_min")
    p.add_argument("--price-max", type=int, default=None, dest="price_max")
    p.add_argument("--transaction", choices=["sale", "rent"], default="sale")
    p.add_argument("--max", type=int, default=100, help="Maks. liczba wyników")
    return p


def main(argv: list[str] | None = None) -> int:
    common.setup_utf8()
    args = build_parser().parse_args(argv)
    records, meta = scrape(args)
    common.emit(records, meta)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
