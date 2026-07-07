"""
scrape_morizon.py — listowanie działek/domów z Morizon.pl.

Mechanika (zweryfikowana empirycznie): strona wyników `https://www.morizon.pl/{dzialki|domy}/{slug}/`
osadza w `<script type="application/ld+json">` obiekt `AggregateOffer` z tablicą `offers[]`, gdzie każda
oferta ma: `name` (z powierzchnią), `price`, `url` (zawiera id `mzn…` i powierzchnię `…m2`), `image`
oraz `itemOffered.address.addressLocality` + `description`. To czytamy — bez kruchego parsowania HTML.

Ograniczenia (świadome, bez cichych limitów — patrz `meta.note`):
- Zwraca PIERWSZĄ stronę wyników (Morizon nie udostępnił prostej paginacji URL; dla górskich miejscowości
  to zwykle komplet).
- Brak filtrów portalowych powierzchni/ceny/promienia — twarde filtrowanie robi pre-screen pipeline'u
  (geo/area/price), a `area`/`price` są w danych oferty (dla `dom` powierzchnia z `name` to pow. BUDYNKU →
  trafia do `raw.house_area_m2`, a `area_m2`=teren pozostaje do uzupełnienia na etapie ingest).
- Współrzędnych brak w wynikach → `lat/lon` puste (uzupełniane przy ingeście; lokalizacja = miejscowość).

Użycie:
  python scrape_morizon.py --location "Kłodzko" --area-min 3000 --price-max 700000 --max 60
  python scrape_morizon.py --location "Walim" --kind dom --max 60
Wynik: JSON {"meta":..., "listings":[...]} na stdout.
"""
from __future__ import annotations

import argparse
import json
import re

import common

KIND_URL_SEG = {"dzialka": "dzialki", "dom": "domy"}


def _ld_aggregate_offers(html: str) -> list[dict]:
    """Zbierz wszystkie offers[] z bloków JSON-LD typu AggregateOffer."""
    out: list[dict] = []

    def walk(o):
        if isinstance(o, dict):
            if o.get("@type") == "AggregateOffer" and isinstance(o.get("offers"), list):
                out.extend(o["offers"])
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
    return out


def normalize(offer: dict, kind: str, transaction: str) -> dict:
    rec = common.empty_record()
    url = offer.get("url") or ""
    mid = re.search(r"(mzn\d+)", url)
    item = offer.get("itemOffered") or {}
    addr = item.get("address") or {}

    rec["source"] = "morizon"
    rec["source_id"] = mid.group(1) if mid else (url or None)
    rec["url"] = url
    rec["title"] = offer.get("name")
    rec["kind"] = kind
    rec["price"] = common.to_int(offer.get("price"))
    rec["transaction"] = transaction
    rec["location"] = {"city": addr.get("addressLocality"), "region": None, "address": None}

    am = re.search(r"-(\d+)m2-mzn", url) or re.search(r"([\d\s]+)\s*m²", offer.get("name") or "")
    area = common.to_int(am.group(1)) if am else None
    if kind == "dom":
        rec["area_m2"] = None  # teren z listingu morizon nieznany (name = pow. budynku)
        rec["raw"] = {"house_area_m2": area}
    else:
        rec["area_m2"] = area
        rec["price_per_m2"] = (rec["price"] // area) if (rec["price"] and area) else None

    img = offer.get("image")
    if isinstance(img, str) and img:
        rec["images"] = [img]
    elif isinstance(img, list):
        rec["images"] = [u for u in img if isinstance(u, str)]
    rec["description"] = item.get("description")
    return rec


def scrape(args) -> tuple[list[dict], dict]:
    seg = KIND_URL_SEG.get(args.kind, "dzialki")
    slug = common.slugify(args.location)
    url = f"https://www.morizon.pl/{seg}/{slug}/"
    meta = {"source": "morizon", "location": args.location, "kind": args.kind,
            "url": url, "transaction": args.transaction,
            "note": "strona 1 wyników; filtry area/price/geo realizuje pre-screen pipeline'u"}

    if args.transaction != "sale":
        meta["error"] = "Morizon scraper obsługuje tylko sprzedaż (sale)."
        return [], meta

    resp = common.http_get(url, accept="text/html")
    if resp.status_code != 200:
        meta["error"] = f"Morizon status {resp.status_code} dla {url} (brak lokalizacji?)"
        return [], meta

    offers = _ld_aggregate_offers(resp.text)
    records = [normalize(o, args.kind, args.transaction) for o in offers]
    records = [r for r in records if r.get("url")]
    records = common.dedupe(records)[: args.max]
    meta["total_available"] = len(offers)
    meta["returned"] = len(records)
    return records, meta


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Listowanie działek/domów z Morizon.pl (JSON-LD).")
    p.add_argument("--location", required=True, help="Miejscowość, np. 'Kłodzko'")
    p.add_argument("--kind", choices=["dzialka", "dom"], default="dzialka")
    p.add_argument("--distance", type=int, default=15, help="(przyjmowane dla zgodności; filtr robi pre-screen)")
    p.add_argument("--area-min", type=int, default=None, dest="area_min")
    p.add_argument("--area-max", type=int, default=None, dest="area_max")
    p.add_argument("--price-min", type=int, default=None, dest="price_min")
    p.add_argument("--price-max", type=int, default=None, dest="price_max")
    p.add_argument("--transaction", choices=["sale", "rent"], default="sale")
    p.add_argument("--max", type=int, default=100)
    return p


def main(argv: list[str] | None = None) -> int:
    common.setup_utf8()
    args = build_parser().parse_args(argv)
    records, meta = scrape(args)
    common.emit(records, meta)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
