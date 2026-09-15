"""
scrape_adresowo.py — listowanie działek z adresowo.pl.

Czym adresowo różni się od pozostałych portali:
- to NIE agregator — ogłoszenia dodają głównie właściciele, oferty pośredników są płatne i można je
  odfiltrować (`--direct-only`, kod `zb` w adresie). Dla nas to inna podaż niż OLX/Otodom/Morizon
  i zwykle bez prowizji;
- wyszukiwanie obsługuje **wiele gmin naraz**, czego portale nie dają: adres ma postać
  `/f/dzialki/<id_gminy>_<id_gminy>_.../<kod_filtrów>`, gdzie `<kod_filtrów>` koduje typy działki
  (`z3`–`z8`) i źródło (`zb` = bezpośrednie). Identyfikatory gmin są wewnętrzne dla portalu i nie
  dają się wyliczyć z nazwy — bierzemy je z GOTOWEGO adresu zapisanego wyszukiwania (patrz niżej);
- paginacja to sufiks `_l2`, `_l3`… doklejany do kodu filtrów.

UWAGA NA JEDNOSTKI (łatwo się na tym przejechać): karta oferty podaje powierzchnię raz w **m²**,
a raz w **ha** — zależnie od wielkości działki. Parser liczący tylko `m²` po cichu gubi WSZYSTKIE
duże działki, czyli dokładnie te, o które chodzi przy powiększaniu areału.

Konfiguracja lokalizacji: `properties/adresowo_searches.json`
    { "Sulejów": "https://adresowo.pl/f/dzialki/182845_.../fz3z4z5z6z7z8zb", ... }
Klucz to nazwa lokalizacji z `criteria.md`. Adres zapisanego wyszukiwania kopiujesz z paska
przeglądarki po ustawieniu filtrów na adresowo.pl. Bez wpisu dla danej lokalizacji scraper próbuje
strony miasta `/dzialki/<slug>/` (istnieje tylko dla większych miejscowości).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import unicodedata

import httpx

import common

BASE = "https://adresowo.pl"
CONFIG = os.path.join(common.PROJECT_DIR, "properties", "adresowo_searches.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36")
MAX_PAGES = 12

# Kody województw w adresach adresowo (odczytane ze strony /dzialki/). Pozwalają ZŁOŻYĆ adres
# wyszukiwania bez klikania w portalu — patrz build_search_url().
WOJ_CODES = {
    "dolnośląskie": "fds", "kujawsko-pomorskie": "fkp", "lubelskie": "flu", "lubuskie": "flb",
    "mazowieckie": "fmz", "małopolskie": "fma", "opolskie": "fop", "podkarpackie": "fpk",
    "podlaskie": "fpd", "pomorskie": "fpm", "warmińsko-mazurskie": "fwn", "wielkopolskie": "fwp",
    "zachodniopomorskie": "fzp", "łódzkie": "fld", "śląskie": "fsl", "świętokrzyskie": "fsk",
}

# Typy działki w kodzie filtrów (z3..z8). Kolejność ustalona empirycznie z adresów portalu.
TYPE_CODES = {
    "budowlana": "z3", "rolno-budowlana": "z4", "siedliskowa": "z5",
    "rolna": "z8", "leśna": "z6", "rekreacyjna": "z7",
}
SRC_DIRECT = "zb"          # Źródło: Bezpośrednie


def build_search_url(voivodeship: str, area_min: int | None = None,
                     price_per_m2_max: int | None = None,
                     types: list[str] | None = None, direct_only: bool = True) -> str | None:
    """Złóż adres wyszukiwania z parametrów zamiast kopiować go z przeglądarki.

    Schemat (rozszyfrowany z adresów portalu i potwierdzony eksperymentem — zmiana każdego członu
    zmienia liczbę wyników w przewidywalny sposób):
        /f/dzialki/<kod_woj><typy><źródło>[_t<min m²>][_u-<max zł/m²>][_lN]
    np. /f/dzialki/fdsz4z5z8zb_t10000_u-5  = dolnośląskie, rolno-bud./siedl./rolna,
        bezpośrednie, od 1 ha, do 5 zł/m².
    """
    code = WOJ_CODES.get(voivodeship.lower())
    if not code:
        return None
    seg = code
    for t in (types or ["rolno-budowlana", "siedliskowa", "rolna"]):
        c = TYPE_CODES.get(t.lower())
        if c:
            seg += c
    if direct_only:
        seg += SRC_DIRECT
    if area_min:
        seg += f"_t{int(area_min)}"
    if price_per_m2_max:
        seg += f"_u-{int(price_per_m2_max)}"
    return f"{BASE}/f/dzialki/{seg}"


def _slug(name: str) -> str:
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def _num(txt: str) -> int | None:
    t = txt.replace(" ", "").replace(" ", "")
    try:
        return int(t)
    except ValueError:
        return None


def _area_m2(card: str) -> int | None:
    """Powierzchnia z karty — obsługuje OBIE jednostki. Pominięcie 'ha' gubi duże działki."""
    m = re.search(r'<span class="font-bold">([\d\s ]+)</span>\s*<span[^>]*>m²', card)
    if m:
        return _num(m.group(1))
    m = re.search(r'<span class="font-bold">([\d\s ,.]+)</span>\s*<span[^>]*>ha', card)
    if m:
        raw = m.group(1).replace(" ", "").replace(" ", "").replace(",", ".")
        try:
            return int(round(float(raw) * 10000))
        except ValueError:
            return None
    return None


def _parse_cards(html: str) -> list[dict]:
    out = []
    for chunk in re.split(r'data-offer-card data-id=', html)[1:]:
        m = re.match(r'"(\d+)"', chunk)
        if not m:
            continue
        oid = m.group(1)
        link = re.search(r'href="(/o/[^"]+)"', chunk)
        price = re.search(r'<span class="font-bold">([\d\s ]+)</span>\s*<span[^>]*>zł', chunk)
        typ = re.search(r'alt="(Działka [a-ząćęłńóśźż-]+)', chunk)
        city = re.search(r'data-track="offer-link">.*?line-clamp-1[^>]*>([^<]+)<', chunk, re.S)
        img = re.search(r'<img src="(https://s\d\.adresowa\.pl/[^"]+)"', chunk)
        out.append({
            "source_id": oid,
            "url": BASE + link.group(1) if link else None,
            "area_m2": _area_m2(chunk),
            "price": _num(price.group(1)) if price else None,
            "plot_type": (typ.group(1).replace("Działka ", "").strip().lower() if typ else None),
            "city": (city.group(1).strip() if city else None),
            "image": img.group(1) if img else None,
        })
    return out


def _fetch(url: str) -> str:
    r = httpx.get(url, headers={"User-Agent": UA}, timeout=45, follow_redirects=True)
    r.raise_for_status()
    # Separator tysięcy w cenach przychodzi jako ENCJA (&nbsp;), nie jako znak \u00a0. Regexy liczące
    # cyfry i spacje gubiłyby wtedy CAŁĄ cenę, a powierzchnie (pisane bez separatora) przechodziłyby —
    # parser wyglądałby na sprawny, zwracając komplet metrów i same puste ceny. Normalizujemy raz, tutaj.
    return r.text.replace("&nbsp;", " ").replace("&#160;", " ")


def _load_config() -> dict:
    """Adresy wyszukiwań: NAJPIERW criteria.md (jedno miejsce, które edytuje użytkownik),
    potem opcjonalny plik JSON. W criteria.md, we frontmatterze:

        adresowo_searches:
          Wleń: "https://adresowo.pl/f/dzialki/fdsz4z5z8zb_t10000_u-5"
    """
    out: dict = {}
    crit = os.path.join(common.PROJECT_DIR, "properties", "criteria.md")
    if os.path.exists(crit):
        try:
            import yaml
            with open(crit, encoding="utf-8") as fh:
                raw = fh.read()
            m = re.match(r"^---\n(.*?)\n---\n", raw, re.S)
            if m:
                fm = yaml.safe_load(m.group(1)) or {}
                out.update({str(k): str(v) for k, v in (fm.get("adresowo_searches") or {}).items()})
        except Exception:  # noqa: BLE001
            pass
    if os.path.exists(CONFIG):
        try:
            with open(CONFIG, encoding="utf-8") as fh:
                for k, v in (json.load(fh) or {}).items():
                    if not k.startswith("_"):
                        out.setdefault(str(k), str(v))
        except Exception:  # noqa: BLE001
            pass
    return out


def _voivodeship_of(location: str) -> str | None:
    """Województwo dla miejscowości — z geokodera (cache na dysku)."""
    try:
        hit = common.osm_lookup(f"{location}, Polska")
        st = ((hit or {}).get("address") or {}).get("state")
        if st:
            return re.sub(r"^wojew[oó]dztwo\s+", "", st.strip(), flags=re.I).lower()
    except Exception:  # noqa: BLE001
        pass
    return None


def _resolve_search_url(location: str, explicit: str | None,
                        area_min: int | None = None,
                        price_per_m2_max: int | None = None) -> tuple[str | None, str]:
    """Zwraca (url, skąd). Kolejność:
    1) --search-url,
    2) wpis w `adresowo_searches` (criteria.md / JSON) — pozwala wskazać KONKRETNE gminy,
       czego nie da się złożyć z samej nazwy (identyfikatory gmin są wewnętrzne dla portalu),
    3) automat: adres dla WOJEWÓDZTWA danej miejscowości + progi z kryteriów,
    4) strona miasta `/dzialki/<slug>/` (istnieje tylko dla większych miejscowości).
    """
    if explicit:
        return explicit.rstrip("/"), "argument --search-url"
    for key, url in _load_config().items():
        if _slug(key) == _slug(location):
            return url.rstrip("/"), "konfiguracja (criteria.md / adresowo_searches.json)"
    woj = _voivodeship_of(location)
    if woj:
        built = build_search_url(woj, area_min, price_per_m2_max)
        if built:
            return built, f"złożony automatycznie dla woj. {woj}"
    return f"{BASE}/dzialki/{_slug(location)}/", "strona miasta (fallback)"


def _page_url(base: str, page: int) -> str:
    if page == 1:
        return base
    if "/f/dzialki/" in base:          # wyszukiwanie filtrowane: sufiks _lN w kodzie filtrów
        return f"{base}_l{page}"
    return f"{base.rstrip('/')}/_l{page}"


def normalize(o: dict, kind: str, transaction: str) -> dict:
    rec = common.empty_record()
    rec["source"] = "adresowo"
    rec["source_id"] = o["source_id"]
    rec["url"] = o["url"]
    rec["title"] = f"Działka {o.get('plot_type') or ''} {o.get('city') or ''}".strip()
    rec["kind"] = kind
    rec["price"] = o.get("price")
    rec["area_m2"] = o.get("area_m2")
    if rec["price"] and rec["area_m2"]:
        rec["price_per_m2"] = round(rec["price"] / rec["area_m2"])
    rec["transaction"] = transaction
    rec["plot_type"] = o.get("plot_type")
    rec["location"] = {"city": o.get("city"), "region": None, "address": None}
    rec["coords_approx"] = True                  # lista nie podaje współrzędnych
    rec["owner_type"] = "private"                # adresowo to głównie oferty bezpośrednie
    rec["images"] = [o["image"]] if o.get("image") else []
    rec["raw"] = {"plot_type_pl": o.get("plot_type")}
    return rec


def _criteria_ppm2() -> int | None:
    """Docelowa cena zł/m² z criteria.md (price_per_m2_max_rolna) — do złożenia adresu."""
    try:
        import yaml
        crit = os.path.join(common.PROJECT_DIR, "properties", "criteria.md")
        m = re.match(r"^---\n(.*?)\n---\n", open(crit, encoding="utf-8").read(), re.S)
        return (yaml.safe_load(m.group(1)) or {}).get("price_per_m2_max_rolna") if m else None
    except Exception:  # noqa: BLE001
        return None


def scrape(args) -> tuple[list[dict], dict]:
    base, origin = _resolve_search_url(args.location, args.search_url,
                                       args.area_min, _criteria_ppm2())
    meta = {"source": "adresowo", "location": args.location, "search_url": base,
            "url_origin": origin,
            "note": ("adresowo = oferty głównie BEZPOŚREDNIO od właścicieli; lista nie ma współrzędnych "
                     "(dystans liczy pre-screen po geokodowaniu miejscowości). Powierzchnia bywa podana "
                     "w ha — parser obsługuje obie jednostki.")}

    raw: dict[str, dict] = {}
    pages = 0
    for page in range(1, MAX_PAGES + 1):
        try:
            html = _fetch(_page_url(base, page))
        except Exception as exc:  # noqa: BLE001
            meta["error"] = f"strona {page}: {exc}"
            break
        cards = _parse_cards(html)
        pages = page
        new = [c for c in cards if c["source_id"] not in raw]
        for c in new:
            raw[c["source_id"]] = c
        if not new:
            break
    meta["pages"] = pages
    meta["found"] = len(raw)

    kept = []
    dropped = {"area": 0, "price": 0}
    for o in raw.values():
        if not o.get("url"):
            continue
        if args.area_min and o.get("area_m2") and o["area_m2"] < args.area_min:
            dropped["area"] += 1
            continue
        if args.area_max and o.get("area_m2") and o["area_m2"] > args.area_max:
            dropped["area"] += 1
            continue
        if args.price_max and o.get("price") and o["price"] > args.price_max:
            dropped["price"] += 1
            continue
        kept.append(o)

    records = [normalize(o, args.kind, args.transaction) for o in kept]
    records = common.dedupe(records)[: args.max]
    meta["dropped"] = dropped
    meta["returned"] = len(records)
    return records, meta


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Listowanie działek z adresowo.pl (oferty bezpośrednie).")
    p.add_argument("--location", required=True, help="Nazwa lokalizacji (klucz w adresowo_searches.json)")
    p.add_argument("--search-url", dest="search_url", default=None,
                   help="Gotowy adres wyszukiwania z adresowo.pl (ma pierwszeństwo nad konfiguracją)")
    p.add_argument("--kind", choices=["dzialka", "dom"], default="dzialka")
    p.add_argument("--distance", type=int, default=15, help="(dla zgodności; filtr robi pre-screen)")
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
