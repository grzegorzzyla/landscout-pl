"""
geoportal_link.py — z identyfikatora działki (TERYT) albo z oferty buduje link do krajowego geoportalu.

Identyfikator TERYT (`<terytGminy>.<obreb>.<nrDziałki>`, np. `020808_5.0003.388/1`) koduje województwo,
powiat, gminę, obręb i numer działki — wszystko, czego potrzebuje geoportal. Działkę uzyskuje skrypt
`geo_analyze.py` (ULDK GUGiK) i zapisuje deep-dive do `parcel` w pliku oferty.

Użycie:
  python geoportal_link.py --parcel-id "020808_5.0003.388/1"
  python geoportal_link.py --id 20260628_003     # czyta parcel.id z oferty
Wyjście (stdout): JSON {parcel_id, geoportal_url, [pola administracyjne z oferty]}.
"""
from __future__ import annotations

import argparse
import json
import sys

import common
from geo_analyze import geoportal_url


def main(argv=None) -> int:
    common.setup_utf8()
    p = argparse.ArgumentParser(description="Zbuduj link do geoportalu z identyfikatora działki / oferty.")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--parcel-id", dest="parcel_id")
    src.add_argument("--id", dest="listing_id", help="ID oferty (czyta parcel.id z .md)")
    args = p.parse_args(argv)

    out: dict = {}
    if args.listing_id:
        import manage_listing as ml
        fm, _ = ml.load_listing(args.listing_id)
        parcel = fm.get("parcel") or {}
        pid = parcel.get("id")
        if not pid:
            sys.stdout.write(json.dumps(
                {"error": f"Oferta {args.listing_id} nie ma parcel.id — uruchom deep-dive."},
                ensure_ascii=False) + "\n")
            return 1
        out = {k: parcel.get(k) for k in
               ("id", "voivodeship", "county", "commune", "region", "obreb_number", "parcel_no")}
        out["parcel_id"] = pid
    else:
        out["parcel_id"] = args.parcel_id

    out["geoportal_url"] = geoportal_url(out["parcel_id"])
    sys.stdout.write(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
