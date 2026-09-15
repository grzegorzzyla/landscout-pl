"""
scrape_kowr.py — listowanie nieruchomości rolnych z zasobu KOWR (nieruchomoscikowr.gov.pl).

Czym się różni od scraperów portali (OLX/Otodom/Morizon):
- to NIE są ogłoszenia sprzedaży z wolnego rynku, tylko **przetargi** na państwową ziemię rolną;
  cena w rekordzie to **cena wywoławcza**, a nie cena transakcyjna (raw.price_kind = "wywoławcza");
- część oferty to **dzierżawa**, nie sprzedaż (raw.distribution); domyślnie zwracamy tylko sprzedaż;
- tytuł oferty zawiera powiat, gminę, obręb i **numer działki** — wyłuskujemy je do raw.parcel_no
  i raw.region_name, bo `geo_analyze.py --parcel-no --region-name` potrafi z nich potwierdzić działkę
  (przy ofertach portalowych numeru zwykle nie ma i współrzędne pozostają orientacyjne);
- portal NIE ma współrzędnych ani działającego filtra lokalizacji w URL (pole `location` jest
  ignorowane — to autouzupełnianie), więc: filtry powierzchni/ceny robimy po stronie serwera,
  a lokalizację dopasowujemy po nazwach z tytułu, po stronie klienta.

Dlatego listing chodzi przez **dzienny cache na dysku** (scripts/.cache/kowr_RRRRMMDD.json):
pełne przejście to ~50 stron, a wyszukiwanie odpytuje ten sam zasób raz na lokalizację.
Pierwsze uruchomienie w danym dniu pobiera całość, kolejne czytają cache.

Wyjście: wspólny schemat rekordu (common.empty_record) + meta — jak pozostałe scrapery.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import time
import unicodedata

import httpx

import common

BASE = "https://www.nieruchomoscikowr.gov.pl/nieruchomosci/oferty"
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")
PER_PAGE = 50          # wyżej portal degraduje do 10/stronę
MAX_PAGES = 60         # bezpiecznik


def _norm(s: str | None) -> str:
    """Bez ogonków, małymi literami — do porównywania nazw miejscowości."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower()


def _money(txt: str) -> int | None:
    m = re.search(r"([\d\s ]+)(?:,\d+)?\s*zł", txt)
    if not m:
        return None
    try:
        return int(re.sub(r"[^\d]", "", m.group(1)))
    except ValueError:
        return None


def _area_m2(txt: str) -> int | None:
    """'2,8520 ha' -> 28520 m²."""
    m = re.search(r"([\d]+(?:[.,]\d+)?)\s*ha", txt)
    if not m:
        return None
    try:
        return int(round(float(m.group(1).replace(",", ".")) * 10000))
    except ValueError:
        return None


# Nie zaczepiamy się o </li> — domknięcie bloku bywa >5000 znaków dalej i zależy od układu strony.
# Segment oferty = od jej linku do linku NASTĘPNEJ oferty (albo do końca listy).
_LINK_RE = re.compile(
    r'<a href="(?P<url>https://www\.nieruchomoscikowr\.gov\.pl/nieruchomosci/oferty/(?P<id>\d+))">'
    r'(?P<title>[^<]+)</a>')


def _field(block: str, label: str) -> str | None:
    m = re.search(re.escape(label) + r":\s*</dt>\s*<dd[^>]*>\s*<b>(.*?)</b>", block, re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else None


_WOJ = ("dolnośląskie kujawsko-pomorskie lubelskie lubuskie łódzkie małopolskie mazowieckie "
        "opolskie podkarpackie podlaskie pomorskie śląskie świętokrzyskie warmińsko-mazurskie "
        "wielkopolskie zachodniopomorskie").split()


def _parse_title(title: str) -> dict:
    """Tytuły KOWR nie mają jednego formatu — spotykane warianty:
    1) 'OT Opole pow. kędzierzyńsko-kozielski, gm. Reńska Wieś, obr. Poborszów dz 324'
    2) 'Oddział Terenowy w Lublinie, województwo LUBELSKIE, powiat puławski, gmina Kurów obręb Dęba, 1.62 ha'
    3) 'OT Częstochowa, śląskie, rybnicki, Czerwionka-Leszczyny, Czerwionka'   (same nazwy po przecinkach)
    4) 'OT Koszalin - Popowo 17/6'                                            (obręb + nr działki)
    5) 'OGŁOSZENIE Nr US/127/068/2026'                                        (bez lokalizacji)
    Etykiety bywają skrócone ('pow.', 'gm.', 'obr.') albo rozpisane ('powiat', 'gmina', 'obręb').
    UWAGA: 'pow.' występuje też w znaczeniu POWIERZCHNI ('o pow. 6,5 ha') — dlatego odrzucamy
    dopasowania zaczynające się od cyfry.
    """
    out: dict = {}
    t = title

    m = re.search(r"\bpow(?:iat)?\.?\s+([^,]+)", t, re.I)
    if m:
        v = m.group(1).strip()
        if v and not v[0].isdigit():                      # nie 'o pow. 6,5 ha'
            out["county"] = re.split(r"\s+(?:gm|gmina)\b", v, flags=re.I)[0].strip()

    m = re.search(r"\bgm(?:ina)?\.?\s+(.+?)(?:\s*,|\s+obr|\s+dz|$)", t, re.I)
    if m:
        out["commune"] = m.group(1).strip()

    m = re.search(r"\bobr(?:[ęe]b)?\.?\s+(.+?)(?:\s*,|\s+dzia[łl]k|\s+dz\.?\s|\s+\d+[.,]\d+\s*ha|$)",
                  t, re.I)
    if m:
        out["region_name"] = m.group(1).strip()

    m = re.search(r"\b(?:dzia[łl]ka\s+nr|dz\.?)\s*([\d]+(?:/\d+)?(?:\s*,\s*[\d]+(?:/\d+)?)*)", t, re.I)
    if m:
        nums = [n.strip() for n in re.split(r"[,\s]+", m.group(1)) if n.strip()]
        if nums:
            out["parcel_no"] = nums

    if out.get("commune") or out.get("region_name"):
        return out

    # --- wariant 3: same nazwy po przecinkach, kotwicą jest nazwa województwa
    parts = [x.strip() for x in t.split(",") if x.strip()]
    woj_norm = {_norm(w) for w in _WOJ}
    for i, x in enumerate(parts):
        if _norm(x) in woj_norm:
            rest = parts[i + 1:]
            for key, val in zip(("county", "commune", "region_name"), rest):
                out[key] = val
            return out

    # --- wariant 4: 'OT <oddział> - <obręb> <nr działki>'
    m = re.search(r"^(?:OT|ODDZIA[ŁL])[^-]*-\s*(?P<name>[^\d]+?)\s*(?P<no>\d+(?:/\d+)?)?\s*$", t, re.I)
    if m:
        nm = (m.group("name") or "").strip(" -,")
        if nm:
            out["region_name"] = nm
        if m.group("no"):
            out["parcel_no"] = [m.group("no")]
    return out


def _fetch_page(page: int, area_min_ha: float | None, price_max: int | None) -> str:
    params = {"per_page": PER_PAGE, "page": page}
    if area_min_ha:
        params["area_min"] = area_min_ha
    if price_max:
        params["starting_price_max_zl"] = price_max
    r = httpx.get(BASE, params=params, timeout=60,
                  headers={"User-Agent": "assistant-properties/1.0 (personal use)"},
                  follow_redirects=True)
    r.raise_for_status()
    return r.text


def _parse_page(html: str) -> list[dict]:
    out = []
    hits = list(_LINK_RE.finditer(html))
    for n, m in enumerate(hits):
        end = hits[n + 1].start() if n + 1 < len(hits) else len(html)
        blk = html[m.end():end]
        title = re.sub(r"\s+", " ", m.group("title")).strip()
        rec = {
            "source_id": m.group("id"),
            "url": m.group("url"),
            "title": title,
            "price": _money(_field(blk, "Cena wywoławcza") or ""),
            "area_m2": _area_m2(_field(blk, "Powierzchnia") or ""),
            "immovable_type": (_field(blk, "Typ nieruchomości") or "").lower() or None,
            "distribution": (_field(blk, "Typ rozdysponowania") or "").lower() or None,
        }
        rec.update(_parse_title(title))
        out.append(rec)
    return out


def load_all(area_min_ha: float | None, price_max: int | None,
             refresh: bool = False) -> tuple[list[dict], dict]:
    """Pełna lista ofert (z dziennym cache). Filtry pow./ceny idą do serwera."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    key = f"kowr_{_dt.date.today():%Y%m%d}_a{area_min_ha or 0}_p{price_max or 0}.json"
    path = os.path.join(CACHE_DIR, key)
    if not refresh and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        return d["offers"], {"cache": "hit", "cached_at": d.get("at"), "pages": d.get("pages")}

    offers: list[dict] = []
    seen: set[str] = set()
    pages = 0
    for page in range(1, MAX_PAGES + 1):
        try:
            html = _fetch_page(page, area_min_ha, price_max)
        except Exception as exc:  # noqa: BLE001
            return offers, {"cache": "partial", "pages": pages, "error": f"strona {page}: {exc}"}
        recs = _parse_page(html)
        pages = page
        if not recs:
            break
        new = [r for r in recs if r["source_id"] not in seen]
        for r in new:
            seen.add(r["source_id"])
        offers.extend(new)
        if len(new) == 0:          # ta sama strona co poprzednio → koniec
            break
        time.sleep(0.4)            # uprzejmie wobec serwera publicznego

    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"at": _dt.datetime.now().isoformat(timespec="seconds"),
                   "pages": pages, "offers": offers}, fh, ensure_ascii=False)
    return offers, {"cache": "miss", "pages": pages}


def _location_names(location: str) -> list[str]:
    """Nazwy do dopasowania: sama miejscowość + jej powiat (żeby złapać sąsiednie gminy).
    Dokładny dystans i tak policzy pre-screen — tu chodzi o sensowny nadzbiór."""
    names = [location]
    try:
        hit = common.osm_lookup(f"{location}, Polska")
        addr = (hit or {}).get("address") or {}
        for k in ("county", "state_district", "municipality"):
            v = addr.get(k)
            if v:
                names.append(re.sub(r"^(powiat|gmina)\s+", "", v, flags=re.I))
    except Exception:  # noqa: BLE001
        pass
    return [n for n in dict.fromkeys(names) if n]


def normalize(o: dict, kind: str, transaction: str) -> dict:
    rec = common.empty_record()
    rec["source"] = "kowr"
    rec["source_id"] = o["source_id"]
    rec["url"] = o["url"]
    rec["title"] = o["title"]
    rec["kind"] = kind
    rec["price"] = o.get("price")
    rec["area_m2"] = o.get("area_m2")
    if rec["price"] and rec["area_m2"]:
        rec["price_per_m2"] = round(rec["price"] / rec["area_m2"])
    rec["transaction"] = "sale" if o.get("distribution") == "sprzedaz" else "rent"
    rec["plot_type"] = o.get("immovable_type")
    rec["location"] = {"city": o.get("region_name") or o.get("commune"),
                       "region": o.get("county"), "address": None}
    rec["coords_approx"] = True          # KOWR nie podaje współrzędnych
    rec["owner_type"] = "kowr"           # Skarb Państwa / zasób KOWR
    rec["description"] = o["title"]
    rec["raw"] = {
        "price_kind": "wywoławcza",
        "distribution": o.get("distribution"),
        "immovable_type": o.get("immovable_type"),
        "commune": o.get("commune"),
        "county": o.get("county"),
        "region_name": o.get("region_name"),
        "parcel_no": o.get("parcel_no"),
        "tender": True,
    }
    return rec


def scrape(args) -> tuple[list[dict], dict]:
    area_min_ha = round(args.area_min / 10000, 4) if args.area_min else None
    offers, cmeta = load_all(area_min_ha, args.price_max, refresh=args.refresh)
    meta = {"source": "kowr", "location": args.location, "kind": args.kind,
            "total_in_zasob": len(offers), **cmeta,
            "note": ("cena = WYWOŁAWCZA (przetarg), nie transakcyjna; filtr lokalizacji po nazwach "
                     "z tytułu (portal nie ma filtra po URL ani współrzędnych) — dokładny dystans "
                     "liczy pre-screen po geokodowaniu obrębu/gminy")}

    names = [_norm(n) for n in _location_names(args.location)]
    meta["matched_names"] = names

    kept = []
    for o in offers:
        if args.transaction == "sale" and o.get("distribution") != "sprzedaz":
            continue
        if args.area_max and o.get("area_m2") and o["area_m2"] > args.area_max:
            continue
        if args.price_min and o.get("price") and o["price"] < args.price_min:
            continue
        # Dopasowanie po CAŁYCH SŁOWACH, nie po podciągu: 'elk' jako podciąg trafia w 'Kukiełki'
        # (Tereszpol w lubelskiem, 500 km od Ełku). Nazwy wieloczłonowe ('bielsk podlaski') dopasowujemy
        # jako sekwencję słów.
        hay = _norm(o.get("title"))
        if not any(n and re.search(r"(?<![a-z0-9])" + re.escape(n) + r"(?![a-z0-9])", hay) for n in names):
            continue
        kept.append(o)

    records = [normalize(o, args.kind, args.transaction) for o in kept]
    records = common.dedupe(records)[: args.max]
    meta["matched"] = len(kept)
    meta["returned"] = len(records)
    return records, meta


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Listowanie nieruchomości rolnych z zasobu KOWR (przetargi).")
    p.add_argument("--location", required=True, help="Miejscowość/gmina/powiat, np. 'Bielsk Podlaski'")
    p.add_argument("--kind", choices=["dzialka", "dom"], default="dzialka")
    p.add_argument("--distance", type=int, default=15, help="(przyjmowane dla zgodności; filtr robi pre-screen)")
    p.add_argument("--area-min", type=int, default=None, dest="area_min", help="m²")
    p.add_argument("--area-max", type=int, default=None, dest="area_max", help="m²")
    p.add_argument("--price-min", type=int, default=None, dest="price_min")
    p.add_argument("--price-max", type=int, default=None, dest="price_max")
    p.add_argument("--transaction", choices=["sale", "rent"], default="sale",
                   help="sale = przetargi na sprzedaż (domyślnie), rent = dzierżawa")
    p.add_argument("--max", type=int, default=100)
    p.add_argument("--refresh", action="store_true", help="wymuś ponowne pobranie (pomiń dzienny cache)")
    return p


def main(argv: list[str] | None = None) -> int:
    common.setup_utf8()
    args = build_parser().parse_args(argv)
    records, meta = scrape(args)
    common.emit(records, meta)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
