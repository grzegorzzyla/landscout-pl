"""
common.py — wspólny fundament skryptów scrapujących i zarządzających działkami.

Zawiera:
- konfigurację UTF-8 stdout (Windows),
- klienta HTTP z nagłówkami przeglądarki i retry,
- slugify dla polskich znaków,
- geokoder Nominatim (z cache na dysku),
- znormalizowany schemat ogłoszenia (normalize/empty_record),
- deduplikację,
- emisję wyniku jako JSON (UTF-8) na stdout.

Wynik scrapera (stdout): {"meta": {...}, "listings": [ <record>, ... ]}
Pojedynczy <record> ma stały schemat (patrz empty_record()).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata
from typing import Any, Iterable

import httpx

# --- katalogi -------------------------------------------------------------
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPTS_DIR)
CACHE_DIR = os.path.join(SCRIPTS_DIR, ".cache")
GEO_CACHE = os.path.join(CACHE_DIR, "geocode.json")


def setup_utf8() -> None:
    """Wymuś UTF-8 na stdout/stderr (konsola Windows bywa cp1250)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass


# --- HTTP -----------------------------------------------------------------
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _headers(accept: str) -> dict[str, str]:
    return {
        "User-Agent": UA,
        "Accept": accept,
        "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.7",
        "Sec-CH-UA": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "Sec-CH-UA-Platform": '"Windows"',
    }


def http_get(
    url: str,
    params: dict[str, Any] | None = None,
    accept: str = "application/json",
    timeout: float = 30.0,
    retries: int = 3,
    backoff: float = 2.0,
) -> httpx.Response:
    """GET z nagłówkami przeglądarki i ponowieniami. Rzuca przy ostatecznej porażce."""
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            r = httpx.get(
                url,
                params=params,
                headers=_headers(accept),
                timeout=timeout,
                follow_redirects=True,
            )
            if r.status_code in (429, 403, 503) and attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
                continue
            return r
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            time.sleep(backoff * (attempt + 1))
    if last_exc:
        raise last_exc
    raise RuntimeError(f"GET nieudany: {url}")


# --- slug / tekst ---------------------------------------------------------
_PL_MAP = str.maketrans("ąćęłńóśżźĄĆĘŁŃÓŚŻŹ", "acelnoszzACELNOSZZ")


def slugify(name: str) -> str:
    """Nazwa miejscowości -> slug (np. 'Wrocław' -> 'wroclaw')."""
    s = name.strip().translate(_PL_MAP)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s


def to_int(value: Any) -> int | None:
    """Wyciągnij liczbę całkowitą z dowolnego formatu ('1 000 m²' -> 1000, '1564.00' -> 1564)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).replace(" ", " ")
    m = re.search(r"\d[\d ]*(?:[.,]\d+)?", s)
    if not m:
        return None
    num = m.group(0).replace(" ", "").replace(",", ".")
    try:
        return int(float(num))
    except ValueError:
        digits = re.sub(r"[^\d]", "", num)
        return int(digits) if digits else None


# --- geokoder (Nominatim) -------------------------------------------------
def _load_geo_cache() -> dict[str, Any]:
    try:
        with open(GEO_CACHE, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _save_geo_cache(cache: dict[str, Any]) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(GEO_CACHE, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, ensure_ascii=False, indent=0)


def osm_lookup(query: str) -> dict[str, Any] | None:
    """Pełny pierwszy wynik Nominatim (lat, lon, address{...}). Cache na dysku."""
    key = "full::" + query.strip().lower()
    cache = _load_geo_cache()
    if key in cache:
        return cache[key]
    try:
        r = httpx.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "json", "limit": 1,
                    "countrycodes": "pl", "addressdetails": 1},
            headers={"User-Agent": "assistant-properties/1.0 (personal use)"},
            timeout=20,
        )
        data = r.json()
        result = data[0] if data else None
    except Exception:
        result = None
    cache[key] = result
    _save_geo_cache(cache)
    time.sleep(1.0)  # Nominatim: max 1 req/s
    return result


def geocode(query: str) -> tuple[float, float] | None:
    """Geokoduj miejscowość/adres -> (lat, lon) przez OpenStreetMap Nominatim. Cache na dysku."""
    res = osm_lookup(query)
    if res and res.get("lat") and res.get("lon"):
        return float(res["lat"]), float(res["lon"])
    return None


# --- znormalizowany schemat ogłoszenia ------------------------------------
def empty_record() -> dict[str, Any]:
    """Stały schemat rekordu zwracanego przez każdy scraper."""
    return {
        "source": None,          # otodom | olx | gethome
        "source_id": None,       # identyfikator w portalu (string)
        "url": None,
        "title": None,
        "kind": "dzialka",       # dzialka | dom — typ nieruchomości (dom obejmuje siedliska/gospodarstwa)
        "price": None,           # PLN (int)
        "price_per_m2": None,    # int
        "area_m2": None,         # int — dla dom: powierzchnia DZIAŁKI (teren); pow. domu w raw.house_area_m2
        "transaction": None,     # sale | rent
        "plot_type": None,       # działka: dzialki-budowlane/rolne/...; dom: typ zabudowy (wolnostojacy/...)
        "location": {"city": None, "region": None, "address": None},
        "lat": None,
        "lon": None,
        "coords_approx": True,   # czy współrzędne są przybliżone (z listingu)
        "owner_type": None,      # private | agency | developer
        "images": [],            # lista URL
        "date_created": None,    # ISO
        "description": None,
        "raw": {},               # surowe pola pomocnicze (lekki podzbiór)
    }


# --- deduplikacja ---------------------------------------------------------
def dedupe(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Usuń duplikaty po (source, source_id); zachowaj kolejność."""
    seen: set[tuple[Any, Any]] = set()
    out: list[dict[str, Any]] = []
    for rec in records:
        key = (rec.get("source"), rec.get("source_id"))
        if key in seen:
            continue
        seen.add(key)
        out.append(rec)
    return out


# --- emisja ---------------------------------------------------------------
def emit(records: list[dict[str, Any]], meta: dict[str, Any] | None = None) -> None:
    """Wypisz wynik jako JSON UTF-8 na stdout."""
    payload = {"meta": meta or {}, "listings": records}
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
    sys.stdout.write("\n")
