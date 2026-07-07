"""
scrape_gethome.py — backupowe listowanie działek z gethome.pl.

Mechanika (zweryfikowana empirycznie):
- strona wyników: https://www.gethome.pl/dzialki/{na-sprzedaz|do-wynajecia}/{slug}/
  ?area_min=..&area_max=..&price_min=..&price_max=..&page=..
- dane w window.__INITIAL_STATE__ (Redux) -> offerList.offers.offers[]
  (mają coordinates.lat/lon — realne, price.total, property.size, pictures[]).

Backup używany, gdy OLX/Otodom dają za mało wyników. city slug dla mniejszych
miejscowości bywa nieobsługiwany — wtedy zwraca pustą listę.
"""
from __future__ import annotations

import argparse
import json
import re

import common

PIC_PREF = ["o_img_960", "o_img_800", "o_img_640", "o_img_500", "o_img_360x171"]


def _extract_initial_state(html_text: str) -> dict | None:
    m = re.search(r"__INITIAL_STATE__\s*=\s*", html_text)
    if not m:
        return None
    start = html_text.find("{", m.end())
    if start < 0:
        return None
    depth = 0
    for j in range(start, len(html_text)):
        ch = html_text[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html_text[start:j + 1])
                except Exception:
                    return None
    return None


def _pick_image(pic: dict) -> str | None:
    for key in PIC_PREF:
        if pic.get(key):
            return pic[key]
    for v in pic.values():
        if isinstance(v, str) and v.startswith("http"):
            return v
    return None


def normalize(offer: dict, transaction: str, kind: str = "dzialka") -> dict:
    rec = common.empty_record()
    price = offer.get("price") or {}
    coords = offer.get("coordinates") or {}
    prop = offer.get("property") or {}
    addr = prop.get("address_details") or {}

    rec["source"] = "gethome"
    rec["source_id"] = str(offer.get("id"))
    rec["url"] = f"https://www.gethome.pl/oferta/{offer.get('slug')}/"
    rec["title"] = offer.get("name")
    rec["kind"] = kind
    rec["price"] = common.to_int(price.get("total"))
    rec["transaction"] = transaction
    if kind == "dom":
        # dom: area_m2 = pow. działki (lot_size); 'size' = pow. domu -> raw
        rec["area_m2"] = common.to_int(prop.get("lot_size"))
        rec["price_per_m2"] = None
        rec["plot_type"] = prop.get("type") or "house"
    else:
        rec["area_m2"] = common.to_int(prop.get("size"))
        rec["price_per_m2"] = common.to_int(price.get("per_sqm"))
        rec["plot_type"] = "lot" if "lot" in (offer.get("offer_type") or []) else None
    rec["location"] = {
        "city": addr.get("city") or prop.get("address"),
        "region": None,
        "address": addr.get("district"),
    }
    if coords.get("lat") and coords.get("lon"):
        rec["lat"] = coords["lat"]
        rec["lon"] = coords["lon"]
        rec["coords_approx"] = False
    rec["owner_type"] = "private" if offer.get("is_private") else "agency"
    rec["images"] = [u for u in (_pick_image(p) for p in (offer.get("pictures") or [])) if u]
    rec["date_created"] = offer.get("created_at")
    rec["description"] = offer.get("description")
    rec["raw"] = {"shape": prop.get("shape")}
    if kind == "dom":
        rec["raw"]["house_area_m2"] = common.to_int(prop.get("size"))
    return rec


def scrape(args) -> tuple[list[dict], dict]:
    seg = "na-sprzedaz" if args.transaction == "sale" else "do-wynajecia"
    cat_seg = "domy" if args.kind == "dom" else "dzialki"
    slug = common.slugify(args.location)
    base = f"https://www.gethome.pl/{cat_seg}/{seg}/{slug}/"
    query = {}
    # dla domów area_* w URL filtruje pow. domu (nie działki) — pomijamy je i filtrujemy
    # po stronie klienta na lot_size; dla działek wysyłamy jak dotychczas
    if args.kind != "dom":
        if args.area_min is not None:
            query["area_min"] = args.area_min
        if args.area_max is not None:
            query["area_max"] = args.area_max
    if args.price_min is not None:
        query["price_min"] = args.price_min
    if args.price_max is not None:
        query["price_max"] = args.price_max

    meta = {"source": "gethome", "location": args.location, "kind": args.kind,
            "transaction": args.transaction, "slug": slug}
    records: list[dict] = []
    page = 1
    page_count = 1
    while len(records) < args.max and page <= page_count:
        q = dict(query, page=page)
        qs = "&".join(f"{k}={v}" for k, v in q.items())
        resp = common.http_get(f"{base}?{qs}", accept="text/html")
        if resp.status_code != 200:
            meta["error"] = f"gethome status {resp.status_code}"
            break
        state = _extract_initial_state(resp.text)
        if not state:
            meta["error"] = "Brak __INITIAL_STATE__ (zmiana struktury lub blokada)."
            break
        offers_node = (state.get("offerList") or {}).get("offers") or {}
        offers = offers_node.get("offers") or []
        page_count = offers_node.get("pageCount", 1) or 1
        if not offers:
            break
        for off in offers:
            rec = normalize(off, args.transaction, args.kind)
            # filtr po stronie klienta (parametry URL gethome bywają zawodne; dla domów area_m2 = pow. działki)
            area, price = rec["area_m2"], rec["price"]
            if args.area_min is not None and (area is None or area < args.area_min):
                continue
            if args.area_max is not None and (area is None or area > args.area_max):
                continue
            if args.price_min is not None and (price is None or price < args.price_min):
                continue
            if args.price_max is not None and (price is None or price > args.price_max):
                continue
            records.append(rec)
        page += 1

    records = common.dedupe(records)[: args.max]
    meta["returned"] = len(records)
    meta["page_count"] = page_count
    return records, meta


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Backupowe listowanie działek z gethome.pl.")
    p.add_argument("--location", required=True)
    p.add_argument("--kind", choices=["dzialka", "dom"], default="dzialka",
                   help="Typ nieruchomości: dzialka (domyślnie) lub dom (obejmuje siedliska/gospodarstwa)")
    p.add_argument("--distance", type=int, default=0, help="(ignorowane — gethome filtruje po mieście)")
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
