"""
ingest_listing.py — zczytanie PEŁNYCH danych z karty ogłoszenia do pliku .md (etap „ingest").

Rozdział etapów: scrapery (scrape_*.py) robią TWARDE filtrowanie na listingu portalu i zwracają
kandydatów (link + pola z listy). Ten skrypt bierze pojedynczy LINK do karty oferty, otwiera ją
(httpx/curl; Otodom z fallbackiem Playwright wewnątrz fetch_listing) i zapisuje komplet danych do
properties/listings/*.md wraz z pełną galerią zdjęć. NIE ocenia — ocenę robi properties-eval na danych
z .md (czyli już z pełnej karty, nie z chudego listingu).

Jest to jeden punkt wejścia używany przez: skill `properties-ingest` (uruchamiany w agentach generycznych,
możliwie z listą linków) oraz endpoint strony (ręczne dodanie linku przez użytkownika).

Źródła bez „pełnej karty" do doczytania (Facebook): post FB nie jest re-fetchowalny po URL (logowanie +
dynamika), a pełną treść mamy już ze skanu (scrape_facebook.py). Dla nich jest ścieżka „z gotowego rekordu"
(--records-file): rekord wchodzi prosto do upsertu (source_type=facebook) + pobranie zdjęć, bez fetch_listing.

Użycie:
  python ingest_listing.py --url <URL> [--added-by search|user] [--score N] [--max-photos 20]
  python ingest_listing.py --urls-file links.txt [--added-by user]      # po jednym URL w linii
  python ingest_listing.py --records-file recs.json [--added-by search] # gotowe rekordy (np. FB)

Wynik (stdout JSON): pojedynczy obiekt lub tablica obiektów:
  {"url","id","created","source","title","photos","error"}
"""
from __future__ import annotations

import argparse
import json
import sys

import common
import fetch_listing
import manage_listing as ml
import fetch_photos


def guess_land_type(rec: dict) -> str | None:
    """Zgrubne rozpoznanie rodzaju działki z karty: siedliskowa | budowlana | rolna (lub None)."""
    pt = (rec.get("plot_type") or "").lower()
    txt = ((rec.get("title") or "") + " " + (rec.get("description") or "")).lower()
    blob = pt + " " + txt
    has = lambda *ks: any(k in blob for k in ks)
    if has("siedlisk", "zagrodow", "gospodarstw"):
        return "siedliskowa"
    if "budowlan" in pt or has("budowlan", "pod zabudowę", "pod zabudowe", "warunki zabudowy",
                               "decyzja o wz", "mpzp", "zabudowy mieszkan", "symbolem mn"):
        return "budowlana"
    if "roln" in pt or has("rolna", "rolne", "grunty orne", "użytki rolne", "łąk", "pastwisk"):
        return "rolna"
    return None


def _fetch_photos_and_landtype(listing_id: str, rec: dict, max_photos: int, out: dict) -> None:
    """Wspólny finał ingestu: idempotentne pobranie galerii + zgadnięcie land_type. Aktualizuje `out`."""
    try:
        # idempotencja: wyczyść dotychczasowe zdjęcia, by ponowny ingest nie dublował galerii
        import os, glob
        dest = os.path.join(ml.PHOTOS_DIR, listing_id)
        if os.path.isdir(dest):
            for f in glob.glob(os.path.join(dest, "*")):
                try:
                    os.remove(f)
                except OSError:
                    pass
        ml.set_field(listing_id, "photos", [])
        added = fetch_photos.fetch(listing_id, None, max_photos)
        fm, _ = ml.load_listing(listing_id)
        out["photos"] = len(fm.get("photos") or [])
        out["photos_added"] = len(added)
        # rodzaj działki — ustaw tylko gdy jeszcze nieoznaczony (nie nadpisuj ręcznego/deep-dive)
        if not fm.get("land_type"):
            lt = guess_land_type(rec)
            if lt:
                ml.set_field(listing_id, "land_type", lt)
                out["land_type"] = lt
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"zdjęcia: {exc}"  # rekord zapisany, zdjęcia częściowe


def ingest_one(url: str, added_by: str = "search", score: int | None = None,
               max_photos: int = 20) -> dict:
    out: dict = {"url": url, "id": None, "created": None, "source": None,
                 "title": None, "photos": 0, "error": None}
    records, meta = fetch_listing.fetch(url)
    out["source"] = meta.get("source")
    if not records:
        out["error"] = meta.get("error") or "brak danych z karty oferty"
        return out
    rec = records[0]
    out["title"] = rec.get("title")
    try:
        listing_id, created = ml.upsert_record(rec, source_type="listing",
                                               score=score, added_by=added_by)
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"zapis .md nieudany: {exc}"
        return out
    out["id"], out["created"] = listing_id, created
    _fetch_photos_and_landtype(listing_id, rec, max_photos, out)
    return out


def ingest_record(rec: dict, added_by: str = "search", score: int | None = None,
                  max_photos: int = 20) -> dict:
    """Ingest z GOTOWEGO rekordu (bez fetch_listing) — dla źródeł bez doczytywalnej karty (Facebook).
    Rekord musi mieć source/source_id (np. source='facebook', source_id='<gid>_<pid>')."""
    out: dict = {"url": rec.get("url"), "id": None, "created": None, "source": rec.get("source"),
                 "title": rec.get("title"), "photos": 0, "error": None}
    if not rec.get("source") or not rec.get("source_id"):
        out["error"] = "rekord bez source/source_id"
        return out
    try:
        listing_id, created = ml.upsert_record(rec, source_type=rec.get("source") or "facebook",
                                               score=score, added_by=added_by)
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"zapis .md nieudany: {exc}"
        return out
    out["id"], out["created"] = listing_id, created
    _fetch_photos_and_landtype(listing_id, rec, max_photos, out)
    return out


def main(argv: list[str] | None = None) -> int:
    common.setup_utf8()
    p = argparse.ArgumentParser(description="Zczytaj pełne dane z karty oferty do .md (ingest).")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--url")
    src.add_argument("--urls-file", dest="urls_file", help="plik z URL-ami (po jednym w linii)")
    src.add_argument("--records-file", dest="records_file",
                     help="JSON z gotowymi rekordami (np. FB) — lista albo {\"listings\":[...]}")
    p.add_argument("--added-by", dest="added_by", choices=["search", "user"], default="search")
    p.add_argument("--score", type=int, default=None)
    p.add_argument("--max-photos", dest="max_photos", type=int, default=20)
    args = p.parse_args(argv)

    if args.url:
        result = ingest_one(args.url, args.added_by, args.score, args.max_photos)
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        return 0 if not result.get("error") else 1

    if args.records_file:
        with open(args.records_file, encoding="utf-8") as fh:
            data = json.load(fh)
        recs = data.get("listings", data) if isinstance(data, dict) else data
        results = [ingest_record(r, args.added_by, args.score, args.max_photos) for r in recs]
        sys.stdout.write(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
        return 0

    with open(args.urls_file, encoding="utf-8") as fh:
        urls = [ln.strip() for ln in fh if ln.strip()]
    results = [ingest_one(u, args.added_by, args.score, args.max_photos) for u in urls]
    sys.stdout.write(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
