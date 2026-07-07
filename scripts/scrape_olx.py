"""
scrape_olx.py — listowanie działek z OLX przez publiczne JSON API.

Mechanika (zweryfikowana empirycznie):
- resolver lokalizacji: strona friendly URL osadza "cityId"/"regionId"
  (np. https://www.olx.pl/nieruchomosci/dzialki/sprzedaz/wroclaw/),
- listing: https://www.olx.pl/api/v1/offers/?category_id=709&city_id=...&distance=...
  + filtry: filter_float_m:from/to (m²), filter_float_price:from/to (PLN),
  filter_enum_type[] (rodzaj działki), paginacja offset/limit.

Dla działek domyślnie zwraca tylko budowlane (pomija ROD/ogródki działkowe);
dla domów (--kind dom) zwraca wszystkie domy (obejmuje siedliska/gospodarstwa).

Użycie:
  python scrape_olx.py --location "Wrocław" --distance 20 \
      --area-min 1000 --area-max 3500 --price-max 700000 --max 100
  python scrape_olx.py --location "Walim" --kind dom --distance 15 \
      --area-min 3000 --price-max 700000 --max 100
Wynik: JSON {"meta":..., "listings":[...]} na stdout.
"""
from __future__ import annotations

import argparse
import re
import sys

import common

OFFERS_API = "https://www.olx.pl/api/v1/offers/"
CATEGORY_DZIALKI = 709  # "Działki i grunty" (sprzedaż) — zweryfikowane
CATEGORY_DOMY = 18       # "Domy" — zweryfikowane empirycznie (friendly URL /nieruchomosci/domy/)

# segment friendly URL i kategoria API wg typu nieruchomości
KIND_URL_SEG = {"dzialka": "dzialki", "dom": "domy"}
KIND_CATEGORY = {"dzialka": CATEGORY_DZIALKI, "dom": CATEGORY_DOMY}

# rodzaje działek (param 'type' w OLX); domyślnie tylko budowlane.
# Dla domów NIE filtrujemy po typie zabudowy — chcemy też stare domy/siedliska/gospodarstwa.
PLOT_TYPES_DEFAULT = ["dzialki-budowlane"]
PLOT_TYPES_ALL = [
    "dzialki-budowlane",
    "dzialki-rolne",
    "dzialki-rolno-budowlane",
    "dzialki-siedliskowe",
    "dzialki-rekreacyjne",
    "dzialki-lesne",
    "dzialki-inwestycyjne",
]


def resolve_location(name: str, transaction: str, kind: str = "dzialka") -> tuple[int | None, int | None]:
    """Z friendly URL wyciągnij (city_id, region_id). city_id jest niezależny od transakcji i kategorii."""
    seg = "sprzedaz" if transaction == "sale" else "wynajem"
    cat_seg = KIND_URL_SEG.get(kind, "dzialki")
    slug = common.slugify(name)
    url = f"https://www.olx.pl/nieruchomosci/{cat_seg}/{seg}/{slug}/"
    resp = common.http_get(url, accept="text/html")
    if resp.status_code != 200:
        return None, None
    text = resp.text
    # JSON jest osadzony jako zescape'owany string: "cityId\":54553 (opcjonalny backslash przed cudzysłowem).
    city = re.search(r'cityId\\?":\s*(\d+)', text) or re.search(r'city_id=(\d+)', text)
    region = re.search(r'regionId\\?":\s*(\d+)', text) or re.search(r'region_id=(\d+)', text)
    city_id = int(city.group(1)) if city else None
    region_id = int(region.group(1)) if region else None
    return city_id, region_id


def _photo_urls(offer: dict) -> list[str]:
    urls = []
    for ph in offer.get("photos", []) or []:
        link = ph.get("link") or ""
        if link:
            urls.append(link.replace("{width}", "1024").replace("{height}", "768"))
    return urls


def _param_map(offer: dict) -> dict[str, dict]:
    return {p.get("key"): (p.get("value") or {}) for p in offer.get("params", []) or []}


def normalize(offer: dict, transaction: str, kind: str = "dzialka") -> dict:
    rec = common.empty_record()
    params = _param_map(offer)
    price = params.get("price", {})
    loc = offer.get("location", {}) or {}
    mp = offer.get("map", {}) or {}

    rec["source"] = "olx"
    rec["source_id"] = str(offer.get("id"))
    rec["url"] = offer.get("url")
    rec["title"] = offer.get("title")
    rec["kind"] = kind
    rec["price"] = common.to_int(price.get("value"))
    if kind == "dom":
        # dom: 'm' = pow. domu, 'area' = pow. działki (teren), 'builttype' = typ zabudowy
        rec["area_m2"] = common.to_int(params.get("area", {}).get("key"))
        rec["plot_type"] = (params.get("builttype", {}) or {}).get("key")
        house_m2 = common.to_int(params.get("m", {}).get("key"))
        rec["price_per_m2"] = None  # dla domu zł/m² odnosi się do pow. domu — nie mieszać z teren
    else:
        rec["area_m2"] = common.to_int(params.get("m", {}).get("key"))
        rec["plot_type"] = (params.get("type", {}) or {}).get("key")
        rec["price_per_m2"] = common.to_int(params.get("price_per_m", {}).get("key"))
        house_m2 = None
    rec["transaction"] = transaction
    rec["location"] = {
        "city": (loc.get("city") or {}).get("name"),
        "region": (loc.get("region") or {}).get("name"),
        "address": (loc.get("district") or {}).get("name"),
    }
    if mp.get("lat") and mp.get("lon"):
        rec["lat"] = mp["lat"]
        rec["lon"] = mp["lon"]
        rec["coords_approx"] = not mp.get("show_detailed", False)
    rec["owner_type"] = "agency" if offer.get("business") else "private"
    rec["images"] = _photo_urls(offer)
    rec["date_created"] = offer.get("created_time")
    rec["description"] = offer.get("description")
    rec["raw"] = {"olx_business": offer.get("business")}
    if kind == "dom" and house_m2 is not None:
        rec["raw"]["house_area_m2"] = house_m2
    return rec


def scrape(args) -> tuple[list[dict], dict]:
    city_id, region_id = resolve_location(args.location, args.transaction, args.kind)
    meta = {
        "source": "olx",
        "location": args.location,
        "kind": args.kind,
        "city_id": city_id,
        "region_id": region_id,
        "transaction": args.transaction,
    }
    if not city_id:
        meta["error"] = f"Nie udało się rozwiązać lokalizacji '{args.location}' w OLX."
        return [], meta

    base = {
        "category_id": KIND_CATEGORY.get(args.kind, CATEGORY_DZIALKI),
        "city_id": city_id,
        "distance": args.distance,
        "sort_by": "created_at:desc",
        "limit": 40,
    }
    # filtr powierzchni: działka -> 'm' (pow. działki); dom -> 'area' (pow. działki/teren, bo 'm' to pow. domu)
    area_key = "filter_float_area" if args.kind == "dom" else "filter_float_m"
    if args.area_min is not None:
        base[f"{area_key}:from"] = args.area_min
    if args.area_max is not None:
        base[f"{area_key}:to"] = args.area_max
    if args.price_min is not None:
        base["filter_float_price:from"] = args.price_min
    if args.price_max is not None:
        base["filter_float_price:to"] = args.price_max
    # filtr rodzaju tylko dla działek; dla domów chcemy pełny przekrój (siedliska/gospodarstwa)
    plot_types = []
    if args.kind == "dzialka":
        plot_types = PLOT_TYPES_ALL if args.all_types else PLOT_TYPES_DEFAULT
        for i, t in enumerate(plot_types):
            base[f"filter_enum_type[{i}]"] = t

    records: list[dict] = []
    offset = 0
    total = None
    while len(records) < args.max:
        params = dict(base, offset=offset)
        resp = common.http_get(OFFERS_API, params=params)
        if resp.status_code != 200:
            meta["error"] = f"OLX offers API status {resp.status_code}"
            break
        data = resp.json()
        total = (data.get("metadata") or {}).get("total_elements")
        batch = data.get("data") or []
        if not batch:
            break
        for offer in batch:
            records.append(normalize(offer, args.transaction, args.kind))
        offset += base["limit"]
        if total is not None and offset >= total:
            break

    records = common.dedupe(records)[: args.max]
    meta["total_available"] = total
    meta["returned"] = len(records)
    meta["plot_types"] = plot_types
    return records, meta


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Listowanie działek z OLX (JSON API).")
    p.add_argument("--location", required=True, help="Miejscowość, np. 'Wrocław'")
    p.add_argument("--kind", choices=["dzialka", "dom"], default="dzialka",
                   help="Typ nieruchomości: dzialka (domyślnie) lub dom (obejmuje siedliska/gospodarstwa)")
    p.add_argument("--distance", type=int, default=15, help="Promień w km")
    p.add_argument("--area-min", type=int, default=None, dest="area_min")
    p.add_argument("--area-max", type=int, default=None, dest="area_max")
    p.add_argument("--price-min", type=int, default=None, dest="price_min")
    p.add_argument("--price-max", type=int, default=None, dest="price_max")
    p.add_argument("--transaction", choices=["sale", "rent"], default="sale")
    p.add_argument("--max", type=int, default=100, help="Maks. liczba wyników")
    p.add_argument("--all-types", action="store_true",
                   help="Wszystkie rodzaje działek (domyślnie tylko budowlane)")
    return p


def main(argv: list[str] | None = None) -> int:
    common.setup_utf8()
    args = build_parser().parse_args(argv)
    if args.transaction == "rent":
        sys.stderr.write("[uwaga] Wynajem działek na OLX jest rzadki; kategoria może być niepełna.\n")
    records, meta = scrape(args)
    common.emit(records, meta)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
