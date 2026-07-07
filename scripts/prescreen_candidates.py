"""
prescreen_candidates.py — TANI filtr kandydatów na danych z LISTINGU, PRZED ingestem pełnych kart.

Cel: nie zczytywać i nie zapisywać do .md ofert, które już na podstawie listingu jednoznacznie nie
spełniają podstawowych kryteriów (geografia / powierzchnia / cena / kategoria). Dzięki temu pełne karty
(i galerie) powstają tylko dla ofert rokujących — bez zaśmiecania bazy setkami pudeł.

Odrzuca kandydata, gdy:
- **geo**: odległość od NAJBLIŻSZEJ lokalizacji docelowej (z criteria.md) > `--max-dist-km` (domyślnie 50 km).
  Brak współrzędnych → NIE odrzuca (zostaje do oceny).
- **area**: `area_m2 < area_min`.
- **price**: `price > price_max` (gdy cena znana).
- **kategoria**: ROD/ogródki działkowe, przemysłowa/usługowa, udział/współwłasność (z `plot_type`/tytułu).

Przy wątpliwości ZACHOWUJE (lepiej zingestować jednego za dużo niż zgubić trafny).

Użycie:
  python prescreen_candidates.py --candidates-file cand.json [--max-dist-km 50]
Wejście: JSON — tablica rekordów albo {"listings":[...]}. Kryteria czytane z properties/criteria.md.
Wyjście (stdout): {"meta":{...,"dropped":{...}}, "kept":[...], "rejected":[{id,reason}...]}
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

import yaml

import common

CRITERIA = os.path.join(common.PROJECT_DIR, "properties", "criteria.md")


def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def load_criteria() -> dict:
    with open(CRITERIA, encoding="utf-8") as fh:
        text = fh.read()
    m = text.split("---", 2)
    fm = yaml.safe_load(m[1]) if len(m) >= 3 else {}
    return fm or {}


def target_coords(criteria: dict) -> list[tuple[float, float]]:
    pts = []
    for loc in criteria.get("locations") or []:
        name = loc.get("name") if isinstance(loc, dict) else str(loc)
        if not name:
            continue
        c = common.geocode(f"{name}, Polska")
        if c:
            pts.append(c)
    return pts


_CAT_BAD = ("rod", "ogród działkow", "ogrod dzialkow", "przemysłow", "przemyslow",
            "usługow", "uslugow", "udział", "udzial", "współwłasn", "wspolwlasn", "magazyn")


def _category_reject(rec: dict) -> bool:
    blob = ((rec.get("plot_type") or "") + " " + (rec.get("title") or "")).lower()
    return any(k in blob for k in _CAT_BAD)


def _known_keys() -> tuple[set, set]:
    """Znane z listings/ ORAZ deleted/ — do odsiewu re-ingestu. Zwraca (zbiór (source, source_id),
    zbiór znormalizowanych URL). URL łapie bliźniaki, którym portal nadał inny source_id (np. Otodom)."""
    try:
        import manage_listing
        keys = manage_listing.known_keys()
        sids = {(k.get("source"), str(k.get("source_id"))) for k in keys}
        urls = {k.get("url") for k in keys if k.get("url")}
        return sids, urls
    except Exception:
        return set(), set()


def _norm_url(url) -> str:
    try:
        import manage_listing
        return manage_listing._norm_url(url)
    except Exception:
        return ""


def prescreen(records: list[dict], criteria: dict, max_dist_km: float) -> dict:
    area_min = criteria.get("area_min")
    price_max = criteria.get("price_max")
    targets = target_coords(criteria)
    known_sids, known_urls = _known_keys()

    kept, rejected, dropped = [], [], {}

    def drop(rec, reason):
        rejected.append({"source": rec.get("source"), "source_id": rec.get("source_id"),
                         "city": (rec.get("location") or {}).get("city"), "reason": reason})
        dropped[reason] = dropped.get(reason, 0) + 1

    for rec in records:
        area = rec.get("area_m2")
        price = rec.get("price")
        # dedup deterministyczny: już w bazie (aktywna) albo skasowana → pomiń (nie re-ingestuj).
        # Sprawdzamy (source, source_id) ORAZ znormalizowany URL (bliźniak z innym source_id, np. Otodom).
        if (rec.get("source"), str(rec.get("source_id"))) in known_sids \
                or (_norm_url(rec.get("url")) in known_urls if rec.get("url") else False):
            drop(rec, "znana"); continue
        if area_min and area and area < area_min:
            drop(rec, "area"); continue
        if price_max and price and price > price_max:
            drop(rec, "price"); continue
        if _category_reject(rec):
            drop(rec, "kategoria"); continue
        lat, lon = rec.get("lat"), rec.get("lon")
        if lat is not None and lon is not None and targets:
            dmin = min(_haversine_km(lat, lon, tlat, tlon) for tlat, tlon in targets)
            if dmin > max_dist_km:
                drop(rec, "geo"); continue
        kept.append(rec)

    return {
        "meta": {"in": len(records), "kept": len(kept), "dropped": dropped,
                 "max_dist_km": max_dist_km, "targets": len(targets)},
        "kept": kept,
        "rejected": rejected,
    }


def main(argv=None) -> int:
    common.setup_utf8()
    p = argparse.ArgumentParser(description="Tani pre-screen kandydatów przed ingestem.")
    p.add_argument("--candidates-file", required=True)
    p.add_argument("--max-dist-km", type=float, default=50.0)
    args = p.parse_args(argv)

    with open(args.candidates_file, encoding="utf-8") as fh:
        data = json.load(fh)
    records = data.get("listings", data) if isinstance(data, dict) else data

    result = prescreen(records, load_criteria(), args.max_dist_km)
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
