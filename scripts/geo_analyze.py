"""
geo_analyze.py — pogłębiona analiza terenowa działki po współrzędnych (rdzeń skilla properties-deep-dive).

Łączy otwarte usługi GUGiK i OpenStreetMap; każda sekcja jest odporna na błędy (zwraca null/uwagę,
nigdy nie wywraca całości). Współrzędne wejściowe: WGS84 (lat/lon) — z pola listingu albo z --lat/--lon.

Zwraca na stdout JSON:
{
  "input": {...},
  "parcel": {id, voivodeship, county, commune, region, parcel_no, srid, centroid_2180:[x,y]} | error,
  "terrain": {elevation_m, slope_pct, aspect, samples:{...}} | error,
  "pois": {railway, supermarket, hospital, water: {name, dist_m, lat, lon} | null},   # UDOGODNIENIA (15 km)
  "nuisances": {railway, road_major, cemetery, farm, industrial, quarry, landfill,      # UCIĄŻLIWOŚCI (2,5 km)
                wastewater, wind, power_line: {what, name, dist_m} | null},
                # odległość do linii (tory/drogi/linie NN) liczona do GEOMETRII, nie do centroidu
  "links": {geoportal, mapy_google, osm, mpzp_hint, rcwin_hint, ekw_hint},
  "notes": [ "..." ]            # czego NIE dało się ustalić automatycznie
}

Źródła:
- Działka + admin:   ULDK GUGiK  (https://uldk.gugik.gov.pl/)        — GetParcelByXY, EPSG:4326 (lon,lat)
- Wysokość terenu:   NMT GUGiK   (https://services.gugik.gov.pl/nmt/) — GetHByXY, EPSG:2180
- POI/odległości:    Overpass API (OpenStreetMap)
Przeznaczenie (MPZP), transakcje (RCiWN) i właściciel (KW) nie mają otwartego API — zwracamy
deep-linki i wskazówki do ręcznej weryfikacji (sekcja "links"/"notes").
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from urllib.parse import quote

import httpx

import common

# --- konwersja WGS84 -> PL-1992 (EPSG:2180), bez zależności pyproj --------
# Transverse Mercator na elipsoidzie GRS80, parametry układu 1992:
#   lon0 = 19°E, k0 = 0.9993, FE = 500000, FN = -5300000, lat0 = 0
def wgs84_to_pl1992(lat: float, lon: float) -> tuple[float, float]:
    a = 6378137.0
    f = 1 / 298.257222101  # GRS80
    e2 = f * (2 - f)
    lon0 = math.radians(19.0)
    k0 = 0.9993
    FE, FN = 500000.0, -5300000.0
    phi = math.radians(lat)
    lam = math.radians(lon)
    n = f / (2 - f)
    # promień południkowy A
    A = a / (1 + n) * (1 + n**2 / 4 + n**4 / 64)
    # szereg na meridian arc (Krüger)
    alpha = [
        n / 2 - 2 / 3 * n**2 + 5 / 16 * n**3,
        13 / 48 * n**2 - 3 / 5 * n**3,
        61 / 240 * n**3,
    ]
    e = math.sqrt(e2)
    t = math.sinh(math.atanh(math.sin(phi)) - e * math.atanh(e * math.sin(phi)))
    xi_p = math.atan2(t, math.cos(lam - lon0))
    eta_p = math.atanh(math.sin(lam - lon0) / math.sqrt(1 + t * t))
    xi = xi_p + sum(alpha[j] * math.sin(2 * (j + 1) * xi_p) * math.cosh(2 * (j + 1) * eta_p)
                    for j in range(3))
    eta = eta_p + sum(alpha[j] * math.cos(2 * (j + 1) * xi_p) * math.sinh(2 * (j + 1) * eta_p)
                      for j in range(3))
    northing = k0 * A * xi + FN
    easting = k0 * A * eta + FE
    # ULDK/NMT XY: x = easting-like (pierwszy człon WKT), y = northing-like (drugi człon)
    return easting, northing


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


# --- link do geoportalu z identyfikatora działki (TERYT) -------------------
def geoportal_url(parcel_id: str | None) -> str | None:
    """Deep-link do krajowego geoportalu z podświetleniem działki po jej identyfikatorze TERYT.
    Identyfikator (woj/powiat/gmina/obręb/nr działki zakodowane w TERYT) zawsze działa też wklejony
    ręcznie w wyszukiwarkę działek geoportalu, gdyby deep-link kiedyś przestał panować."""
    if not parcel_id:
        return None
    return "https://mapy.geoportal.gov.pl/imap/Imgp_2.html?gpmap=gp0&identifyParcel=" + quote(parcel_id, safe="")


# --- ULDK: działka + jednostki administracyjne ----------------------------
def fetch_parcel(lat: float, lon: float) -> dict:
    try:
        r = common.http_get(
            "https://uldk.gugik.gov.pl/",
            params={"request": "GetParcelByXY", "xy": f"{lon},{lat},4326",
                    "result": "id,voivodeship,county,commune,region,parcel,geom_wkt"},
            accept="text/plain", retries=3,
        )
        text = r.text.strip()
        lines = text.splitlines()
        if not lines or not lines[0].startswith("0"):
            return {"error": f"ULDK: brak działki dla punktu ({text[:80]})"}
        row = lines[1] if len(lines) > 1 else ""
        cols = row.split("|")
        pid = cols[0] if len(cols) > 0 else None
        # TERYT działki: <terytGminy>.<obreb>.<nrDziałki> (np. 020808_5.0003.388/1)
        idparts = (pid or "").split(".")
        out: dict = {
            "id": pid,
            "voivodeship": cols[1] if len(cols) > 1 else None,
            "county": cols[2] if len(cols) > 2 else None,
            "commune": cols[3] if len(cols) > 3 else None,
            "region": cols[4] if len(cols) > 4 else None,       # nazwa obrębu
            "parcel_no": cols[5] if len(cols) > 5 else None,
            "teryt_gmina": idparts[0] if len(idparts) > 0 else None,
            "obreb_number": idparts[1] if len(idparts) > 1 else None,
            "geoportal_url": geoportal_url(pid),
            "srid": 2180,
        }
        wkt = cols[6] if len(cols) > 6 else ""
        cx, cy, area = _wkt_centroid_area(wkt)
        out["centroid_2180"] = [round(cx, 2), round(cy, 2)] if cx is not None else None
        out["area_m2_geom"] = round(area) if area else None
        return out
    except Exception as e:  # noqa: BLE001
        return {"error": f"ULDK: {e}"}


def _poly_metrics_4326(wkt: str) -> dict | None:
    """Z WKT POLYGON w EPSG:4326 (pary 'lon lat') policz: centroid (lat/lon), pole w m² i centroid w
    PL-1992 (do NMT). Pole liczone po przeliczeniu wierzchołków WGS84→2180 (shoelace)."""
    m = re.search(r"POLYGON\s*\(\(([^)]+)\)\)", wkt)
    if not m:
        return None
    verts = []
    for pair in m.group(1).split(","):
        parts = pair.strip().split()
        if len(parts) >= 2:
            verts.append((float(parts[0]), float(parts[1])))  # (lon, lat)
    if len(verts) >= 2 and verts[0] == verts[-1]:
        verts = verts[:-1]  # odrzuć domykający duplikat
    if len(verts) < 3:
        return None
    clon = sum(v[0] for v in verts) / len(verts)
    clat = sum(v[1] for v in verts) / len(verts)
    xy = [wgs84_to_pl1992(lat, lon) for (lon, lat) in verts]
    area = 0.0
    for i in range(len(xy)):
        x1, y1 = xy[i]
        x2, y2 = xy[(i + 1) % len(xy)]
        area += x1 * y2 - x2 * y1
    cx, cy = wgs84_to_pl1992(clat, clon)
    return {"lat": clat, "lon": clon, "area_m2": abs(area) / 2.0, "centroid_2180": [round(cx, 2), round(cy, 2)]}


def fetch_parcel_by_id(full_id: str) -> dict:
    """ULDK GetParcelById po pełnym identyfikatorze TERYT (gmina.obreb.nr) — geometria w EPSG:4326.
    Deterministyczne rozwiązanie numeru działki (podanego wprost w ogłoszeniu) na REALNE współrzędne."""
    try:
        r = common.http_get(
            "https://uldk.gugik.gov.pl/",
            params={"request": "GetParcelById", "id": full_id,
                    "result": "id,voivodeship,county,commune,region,parcel,geom_wkt", "srid": "4326"},
            accept="text/plain", retries=2,
        )
        lines = r.text.strip().splitlines()
        if not lines or not lines[0].startswith("0"):
            return {"error": f"ULDK GetParcelById: brak działki {full_id} ({r.text[:60]})"}
        cols = (lines[1] if len(lines) > 1 else "").split("|")
        pid = cols[0] if cols else full_id
        out = {
            "id": pid,
            "voivodeship": cols[1] if len(cols) > 1 else None,
            "county": cols[2] if len(cols) > 2 else None,
            "commune": cols[3] if len(cols) > 3 else None,
            "region": cols[4] if len(cols) > 4 else None,
            "parcel_no": cols[5] if len(cols) > 5 else None,
            "geoportal_url": geoportal_url(pid),
        }
        met = _poly_metrics_4326(cols[6] if len(cols) > 6 else "")
        if met:
            out["lat"], out["lon"] = round(met["lat"], 6), round(met["lon"], 6)
            out["area_m2_geom"] = round(met["area_m2"])
            out["centroid_2180"] = met["centroid_2180"]
        return out
    except Exception as e:  # noqa: BLE001
        return {"error": f"ULDK GetParcelById {full_id}: {e}"}


def fetch_parcels_by_name_nr(name_nr: str) -> list[dict]:
    """ULDK GetParcelByIdOrNr po 'Nazwa_obrębu Numer' (np. 'Bartnica 18/5') — geometria w EPSG:4326.
    Numer działki z ogłoszenia ma PIERWSZEŃSTWO nad współrzędnymi z portalu (te bywają adresem agencji).
    Zwraca LISTĘ kandydatów: nazwa obrębu bywa niejednoznaczna w skali kraju (jest wiele „Świerków"),
    więc wybór właściwego zostawia się walidacji (powiat spod współrzędnych + powierzchnia z oferty)."""
    try:
        r = common.http_get(
            "https://uldk.gugik.gov.pl/",
            params={"request": "GetParcelByIdOrNr", "id": name_nr,
                    "result": "id,voivodeship,county,commune,region,parcel,geom_wkt", "srid": "4326"},
            accept="text/plain", retries=2,
        )
        lines = r.text.strip().splitlines()
        # GetParcelByIdOrNr: 1. wiersz = LICZBA znalezionych działek (inaczej niż GetParcelById, gdzie to '0'/status)
        if not lines or not lines[0].strip().isdigit():
            return []
        n = int(lines[0].strip())
        out: list[dict] = []
        for row in lines[1:1 + n]:
            cols = row.split("|")
            if not cols or not cols[0]:
                continue
            pid = cols[0]
            rec = {
                "id": pid,
                "voivodeship": cols[1] if len(cols) > 1 else None,
                "county": cols[2] if len(cols) > 2 else None,
                "commune": cols[3] if len(cols) > 3 else None,
                "region": cols[4] if len(cols) > 4 else None,
                "parcel_no": cols[5] if len(cols) > 5 else None,
                "geoportal_url": geoportal_url(pid),
            }
            met = _poly_metrics_4326(cols[6] if len(cols) > 6 else "")
            if met:
                rec["lat"], rec["lon"] = round(met["lat"], 6), round(met["lon"], 6)
                rec["area_m2_geom"] = round(met["area_m2"])
                rec["centroid_2180"] = met["centroid_2180"]
            out.append(rec)
        return out
    except Exception:  # noqa: BLE001
        return []


def _pick_candidate(cands: list[dict], admin: dict, offer_area: float | None) -> dict | None:
    """Z listy kandydatów (ta sama nazwa obrębu w różnych powiatach) wybierz właściwego:
    silny sygnał = ta sama gmina/powiat/woj. co punkt ze współrzędnych; dodatkowy = zgodność pola z ofertą.
    Bez żadnego sygnału i przy >1 kandydacie NIE zgaduje (zwraca None)."""
    if not cands:
        return None
    adm_teryt = (admin or {}).get("teryt_gmina")
    adm_county = (admin or {}).get("county")
    adm_voiv = (admin or {}).get("voivodeship")

    def score(c: dict) -> int:
        s = 0
        if adm_teryt and str(c.get("id", "")).startswith(adm_teryt + "."):
            s += 100                                    # ta sama gmina (TERYT) — najmocniejszy sygnał
        if adm_county and c.get("county") == adm_county:
            s += 40
        if adm_voiv and c.get("voivodeship") == adm_voiv:
            s += 20
        geom = c.get("area_m2_geom")
        if offer_area and geom:
            diff = abs(geom - offer_area) / offer_area
            if diff <= 0.15:
                s += 30
            elif diff <= 0.30:
                s += 10
        return s

    best = max(cands, key=score)
    if score(best) > 0:
        return best
    # brak jakiegokolwiek sygnału zgodności:
    if not admin:                                       # brak współrzędnych do walidacji — 1 kandydat OK, wiele = nie zgaduj
        return cands[0] if len(cands) == 1 else None
    return None                                         # mamy współrzędne, a kandydat ich NIE potwierdza (inne woj./powiat, pole ≠) → nie ryzykuj


def _wkt_centroid_area(wkt: str) -> tuple[float | None, float | None, float | None]:
    """Średnia wierzchołków (przybliżony centroid) + pole wielokąta z WKT POLYGON w EPSG:2180."""
    m = re.search(r"POLYGON\s*\(\(([^)]+)\)\)", wkt)
    if not m:
        return None, None, None
    pts = []
    for pair in m.group(1).split(","):
        parts = pair.strip().split()
        if len(parts) >= 2:
            pts.append((float(parts[0]), float(parts[1])))
    if len(pts) < 3:
        return None, None, None
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    # pole metodą trapezów (shoelace)
    area = 0.0
    for i in range(len(pts) - 1):
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        area += x1 * y2 - x2 * y1
    return cx, cy, abs(area) / 2.0


# --- NMT: wysokość, nachylenie, ekspozycja --------------------------------
def _nmt_height(northing: float, easting: float) -> float | None:
    """Wysokość z NMT GUGiK. UWAGA na kolejność osi: w PL-1992 (EPSG:2180) X = NORTHING,
    Y = EASTING, i tak samo rozumie je usługa GetHByXY. Tymczasem `wgs84_to_pl1992()` zwraca
    (easting, northing) — podanie ich wprost jako x/y daje wysokość zupełnie innego miejsca
    albo 0.0 (punkt poza zasięgiem NMT). Dlatego ta funkcja przyjmuje (northing, easting)."""
    try:
        r = common.http_get("https://services.gugik.gov.pl/nmt/",
                            params={"request": "GetHByXY", "x": northing, "y": easting},
                            accept="text/plain", retries=2)
        val = r.text.strip()
        if not re.match(r"^-?\d+(\.\d+)?$", val):
            return None
        h = float(val)
        # NMT poza zasięgiem zwraca dokładne 0 — w Polsce żaden punkt lądowy nie ma dokładnie 0,0 m
        # (minimum to ok. -1,8 m pod Elblągiem), więc traktujemy to jako brak odczytu, nie jako "poziom morza".
        return None if h == 0.0 else h
    except Exception:
        return None


_ASPECTS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def fetch_terrain(centroid_2180: list[float] | None) -> dict:
    if not centroid_2180:
        return {"error": "brak centroidu działki (NMT pominięte)"}
    easting, northing = centroid_2180      # wgs84_to_pl1992() zwraca (easting, northing)
    d = 30.0  # m
    h_c = _nmt_height(northing, easting)
    # próbki: E/W przesuwają EASTING, N/S przesuwają NORTHING
    h_e = _nmt_height(northing, easting + d)
    h_w = _nmt_height(northing, easting - d)
    h_n = _nmt_height(northing + d, easting)
    h_s = _nmt_height(northing - d, easting)
    if h_c is None:
        return {"error": "NMT: brak odczytu wysokości dla punktu (poza zasięgiem lub usługa niedostępna)"}
    out: dict = {"elevation_m": round(h_c, 1),
                 "samples": {"C": h_c, "E": h_e, "W": h_w, "N": h_n, "S": h_s}}
    if None in (h_e, h_w, h_n, h_s):
        out["note"] = "częściowy NMT — nachylenie/ekspozycja przybliżone lub pominięte"
        return out
    # gradient (spadek w dół): dz/dx, dz/dy
    dzdx = (h_e - h_w) / (2 * d)  # wzrost ku E
    dzdy = (h_n - h_s) / (2 * d)  # wzrost ku N
    slope = math.sqrt(dzdx**2 + dzdy**2)
    out["slope_pct"] = round(slope * 100, 1)
    out["slope_deg"] = round(math.degrees(math.atan(slope)), 1)
    # ekspozycja = kierunek, w którym teren OPADA (downhill) = przeciwny do gradientu wzrostu
    if slope < 0.01:
        out["aspect"] = "płaski"
    else:
        ang = math.degrees(math.atan2(-dzdx, -dzdy)) % 360  # 0=N, 90=E
        out["aspect"] = _ASPECTS[int((ang + 22.5) % 360 // 45)]
        out["aspect_deg"] = round(ang)
    return out


# --- Overpass: najbliższe POI (jedno łączone zapytanie) -------------------
_OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]


def _classify(tags: dict) -> str | None:
    if tags.get("railway") in ("station", "halt"):
        return "railway"
    if tags.get("shop") == "supermarket":
        return "supermarket"
    if tags.get("amenity") == "hospital":
        return "hospital"
    if tags.get("natural") == "water" or tags.get("leisure") == "swimming_area":
        return "water"
    return None


def _overpass_query(lat: float, lon: float, radius: int) -> list[dict]:
    """Jedno zapytanie o wszystkie kategorie POI; retry + fallback endpoint."""
    a = f"(around:{radius},{lat},{lon})"
    q = (
        "[out:json][timeout:90];("
        f"node[railway=station]{a};node[railway=halt]{a};"
        f"nwr[shop=supermarket]{a};"
        f"nwr[amenity=hospital]{a};"
        f"way[natural=water]{a};relation[natural=water]{a};way[leisure=swimming_area]{a};"
        ");out center tags;"
    )
    last = ""
    for url in _OVERPASS_ENDPOINTS:
        for attempt in range(2):
            try:
                r = httpx.post(url, data={"data": q},
                               headers={"User-Agent": "assistant-properties/1.0 (personal use)"},
                               timeout=150)
                return r.json().get("elements", [])
            except Exception as e:  # noqa: BLE001 (np. 429 → tekst, nie JSON)
                last = str(e)
    raise RuntimeError(last or "Overpass: brak odpowiedzi")


def fetch_pois(lat: float, lon: float, radius: int = 15000) -> dict:
    cats = ["railway", "supermarket", "hospital", "water"]
    out: dict = {c: None for c in cats}
    try:
        elems = _overpass_query(lat, lon, radius)
    except Exception as e:  # noqa: BLE001
        return {c: {"error": f"Overpass: {e}"} for c in cats}
    for el in elems:
        tags = el.get("tags") or {}
        cat = _classify(tags)
        if not cat:
            continue
        elat = el.get("lat") or (el.get("center") or {}).get("lat")
        elon = el.get("lon") or (el.get("center") or {}).get("lon")
        if elat is None or elon is None:
            continue
        dist = round(haversine_m(lat, lon, elat, elon))
        cur = out[cat]
        if cur is None or dist < cur["dist_m"]:
            out[cat] = {"name": tags.get("name"), "dist_m": dist, "lat": elat, "lon": elon,
                        "tags": {k: v for k, v in tags.items()
                                 if k in ("name", "operator", "brand", "railway", "amenity", "shop")}}
    return out


# --- Overpass: UCIĄŻLIWOŚCI (to, o czym ogłoszenie milczy) ----------------
# Osobne zapytanie w MAŁYM promieniu — inaczej niż POI (udogodnienia, 15 km), bo tu liczy się
# bezpośrednie sąsiedztwo. Dla linii (tory, drogi) liczymy odległość do GEOMETRII, nie do centroidu:
# centroid 20-kilometrowej linii kolejowej potrafi leżeć kilkanaście km od działki, przez którą ta linia
# przechodzi 200 m obok.
_NUISANCE_LABELS = {
    "railway":    "czynna linia kolejowa",
    "road_major": "droga ekspresowa/krajowa (motorway/trunk/primary)",
    "road_build": "droga w budowie",
    "cemetery":   "cmentarz",
    "farm":       "zabudowa zagrodowa / budynek gospodarczy (możliwa hodowla)",
    "industrial": "teren przemysłowy / zakład",
    "quarry":     "wyrobisko / żwirownia / kopalnia odkrywkowa",
    "landfill":   "składowisko odpadów",
    "wastewater": "oczyszczalnia ścieków",
    "wind":       "turbina wiatrowa",
    "power_line": "linia wysokiego napięcia",
}

# progi ostrzegawcze (m) — przekroczenie generuje wpis w notes
_NUISANCE_ALERT_M = {
    "railway": 2000, "road_major": 1000, "road_build": 1500, "cemetery": 150,
    "farm": 500, "industrial": 1000, "quarry": 1500, "landfill": 2000,
    "wastewater": 1000, "wind": 1000, "power_line": 200,
}


def _classify_nuisance(tags: dict) -> str | None:
    rw = tags.get("railway")
    if rw == "rail" and tags.get("service") not in ("yard", "siding", "spur"):
        return "railway"
    hw = tags.get("highway")
    if hw in ("motorway", "trunk", "primary"):
        return "road_major"
    if hw == "construction" and tags.get("construction") in ("motorway", "trunk", "primary"):
        return "road_build"
    lu = tags.get("landuse")
    if lu == "cemetery" or tags.get("amenity") == "grave_yard":
        return "cemetery"
    if lu == "farmyard" or tags.get("building") in ("farm_auxiliary", "barn", "cowshed"):
        return "farm"
    if lu == "industrial" or tags.get("man_made") == "works":
        return "industrial"
    if lu == "quarry":
        return "quarry"
    if lu == "landfill":
        return "landfill"
    if tags.get("man_made") == "wastewater_plant":
        return "wastewater"
    if tags.get("generator:source") == "wind" or tags.get("power") == "generator" and tags.get("generator:method") == "wind_turbine":
        return "wind"
    if tags.get("power") == "line":
        return "power_line"
    return None


def _min_dist_to_element(lat: float, lon: float, el: dict) -> float | None:
    """Najmniejsza odległość do elementu: po geometrii (way/relation) albo po punkcie."""
    best = None
    for pt in (el.get("geometry") or []):
        if pt.get("lat") is None:
            continue
        d = haversine_m(lat, lon, pt["lat"], pt["lon"])
        if best is None or d < best:
            best = d
    if best is not None:
        return best
    elat = el.get("lat") or (el.get("center") or {}).get("lat")
    elon = el.get("lon") or (el.get("center") or {}).get("lon")
    if elat is None or elon is None:
        return None
    return haversine_m(lat, lon, elat, elon)


def fetch_nuisances(lat: float, lon: float, radius: int = 2500) -> dict:
    """Najbliższe źródła hałasu/odoru/uciążliwości w promieniu `radius` (domyślnie 2,5 km)."""
    a = f"(around:{radius},{lat},{lon})"
    q = (
        "[out:json][timeout:90];("
        f"way[railway=rail]{a};"
        f"way[highway~\"^(motorway|trunk|primary)$\"]{a};"
        f"way[highway=construction]{a};"
        f"nwr[landuse=cemetery]{a};nwr[amenity=grave_yard]{a};"
        f"nwr[landuse=farmyard]{a};way[building=farm_auxiliary]{a};way[building=barn]{a};"
        f"nwr[landuse=industrial]{a};nwr[man_made=works]{a};"
        f"nwr[landuse=quarry]{a};nwr[landuse=landfill]{a};"
        f"nwr[man_made=wastewater_plant]{a};"
        f"node[\"generator:source\"=wind]{a};"
        f"way[power=line]{a};"
        ");out geom tags;"
    )
    last = ""
    elems = None
    for url in _OVERPASS_ENDPOINTS:
        for _ in range(2):
            try:
                r = httpx.post(url, data={"data": q},
                               headers={"User-Agent": "assistant-properties/1.0 (personal use)"},
                               timeout=150)
                elems = r.json().get("elements", [])
                break
            except Exception as e:  # noqa: BLE001
                last = str(e)
        if elems is not None:
            break
    if elems is None:
        return {"error": f"Overpass (uciążliwości): {last or 'brak odpowiedzi'}"}

    out: dict = {}
    for el in elems:
        tags = el.get("tags") or {}
        cat = _classify_nuisance(tags)
        if not cat:
            continue
        d = _min_dist_to_element(lat, lon, el)
        if d is None:
            continue
        d = round(d)
        cur = out.get(cat)
        if cur is None or d < cur["dist_m"]:
            out[cat] = {"what": _NUISANCE_LABELS[cat], "name": tags.get("name"),
                        "dist_m": d, "ref": tags.get("ref")}
    out["_radius_m"] = radius
    return out


def nuisance_notes(nui: dict) -> list[str]:
    """Zamienia zbyt bliskie uciążliwości na czytelne ostrzeżenia."""
    notes: list[str] = []
    if not isinstance(nui, dict) or "error" in nui:
        return notes
    for cat, thr in _NUISANCE_ALERT_M.items():
        v = nui.get(cat)
        if isinstance(v, dict) and v.get("dist_m") is not None and v["dist_m"] <= thr:
            nm = f" ({v['name']})" if v.get("name") else ""
            notes.append(f"UWAGA: {_NUISANCE_LABELS[cat]}{nm} w odległości {v['dist_m']} m.")
    if isinstance(nui.get("cemetery"), dict) and nui["cemetery"]["dist_m"] < 150:
        notes.append("Cmentarz bliżej niż 150 m — wg § 3 rozp. MGK z 25.08.1959 (Dz.U. 1959/52/315) "
                     "to odległość minimalna dla zabudowy mieszkalnej ORAZ studni; redukcja do 50 m "
                     "wymaga sieci wodociągowej i podłączenia wszystkich budynków (czyli bez studni).")
    return notes


# --- deep-linki / wskazówki do ręcznej weryfikacji ------------------------
def build_links(lat: float, lon: float, parcel: dict) -> dict:
    pid = parcel.get("id") if isinstance(parcel, dict) else None
    return {
        "geoportal": geoportal_url(pid) or "https://mapy.geoportal.gov.pl/",
        "geoportal_point": f"https://www.google.com/maps?q={lat},{lon}",
        "osm": f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=16/{lat}/{lon}",
        "mpzp_hint": ("Sprawdź MPZP/decyzję WZ w geoportalu gminy "
                      f"({parcel.get('commune') if isinstance(parcel, dict) else ''}) "
                      "lub warstwę 'Planowanie przestrzenne' na mapy.geoportal.gov.pl"),
        "rcwin_hint": ("Ceny transakcyjne (RCiWN): warstwa w geoportalu powiatowym/krajowym "
                       "wymaga zwykle logowania/uprawnień — weryfikacja ręczna."),
        "ekw_hint": ("Właściciel: portal Elektronicznych Ksiąg Wieczystych "
                     "(przegladarka-ekw.ms.gov.pl) wymaga numeru KW — poproś sprzedającego "
                     "o nr KW lub ustal w starostwie. Brak otwartego API."),
    }


def analyze(lat: float, lon: float, radius: int = 15000, skip_pois: bool = False,
            offer_area: float | None = None, parcel_nos: list[str] | None = None,
            region_names: list[str] | None = None, nuisance_radius: int = 2500) -> dict:
    notes: list[str] = []
    # by-XY: jednostki administracyjne (gmina/obręb) z okolicy punktu z ogłoszenia. Sam nr działki z
    # tego wywołania jest niewiarygodny (punkt = centroid miejscowości / adres agencji), ale gmina/powiat
    # zwykle są właściwe — służą do WALIDACJI działki rozwiązanej po numerze.
    by_xy = fetch_parcel(lat, lon)
    if "error" in by_xy:
        notes.append(by_xy["error"])
    admin = by_xy if "error" not in by_xy else {}

    # DETERMINISTYCZNE rozwiązanie numeru(ów) działki podanych WPROST w ogłoszeniu (wyłuskuje je skill/LLM
    # i podaje przez --parcel-no; nazwę obrębu/miejscowości przez --region-name). NUMER MA PIERWSZEŃSTWO
    # NAD WSPÓŁRZĘDNYMI z portalu, więc kolejność:
    #   1) nazwa obrębu + numer (GetParcelByIdOrNr) — walidacja powiatem spod współrzędnych + polem z oferty,
    #   2) fallback: obręb spod współrzędnych + numer (GetParcelById) — gdy nazwa nie zadziałała/nie podano.
    resolved: list[dict] = []
    if parcel_nos:
        # kandydaci nazw obrębu: najpierw jawnie podane, potem miejscowość spod współrzędnych (bywa == obręb)
        name_cands = [n for n in (region_names or []) if n and n.strip()]
        if admin.get("region") and admin["region"] not in name_cands:
            name_cands.append(admin["region"])
        for no in parcel_nos:
            cand: dict | None = None
            via = None
            for nm in name_cands:
                picked = _pick_candidate(fetch_parcels_by_name_nr(f"{nm} {no}"), admin, offer_area)
                if picked:
                    cand, via = picked, f'nazwa obrębu „{nm}” + nr'
                    break
            if not cand and admin.get("teryt_gmina") and admin.get("obreb_number"):
                res = fetch_parcel_by_id(f"{admin['teryt_gmina']}.{admin['obreb_number']}.{no}")
                if "error" not in res:
                    cand, via = res, "obręb spod współrzędnych + nr"
            if cand:
                cand["_via"] = via
                resolved.append(cand)
            else:
                notes.append(f"Nie rozwiązano nr działki {no} — ani po nazwie obrębu "
                             f"({', '.join(name_cands) or 'brak nazwy'}), ani spod współrzędnych.")

    eff_lat, eff_lon = lat, lon
    centroid = None
    if resolved:
        # POZYCJĘ OKREŚLA DZIAŁKA Z GEOPORTALU (nie współrzędne z ogłoszenia — te są orientacyjne).
        first = resolved[0]
        eff_lat, eff_lon = first.get("lat", lat), first.get("lon", lon)
        centroid = first.get("centroid_2180")
        area_total = sum(r.get("area_m2_geom") or 0 for r in resolved) or None
        # TERYT gminy/obrębu z ID ROZWIĄZANEJ działki (a NIE z by-XY — obręb bywa inny niż spod współrzędnych)
        idparts = str(first.get("id") or "").split(".")
        via = first.get("_via") or "ULDK"
        parcel = {
            "id": first.get("id"),
            "voivodeship": first.get("voivodeship"), "county": first.get("county"),
            "commune": first.get("commune"), "region": first.get("region"),
            "parcel_no": ", ".join(r.get("parcel_no") for r in resolved if r.get("parcel_no")),
            "teryt_gmina": idparts[0] if len(idparts) > 0 else admin.get("teryt_gmina"),
            "obreb_number": idparts[1] if len(idparts) > 1 else admin.get("obreb_number"),
            "geoportal_url": first.get("geoportal_url"),
            "parcels": [{"parcel_no": r.get("parcel_no"), "id": r.get("id"),
                         "geoportal_url": r.get("geoportal_url"), "area_m2_geom": r.get("area_m2_geom"),
                         "lat": r.get("lat"), "lon": r.get("lon")} for r in resolved],
            "area_m2_geom": area_total,
            "area_m2_offer": round(offer_area) if offer_area else None,
            "lat": round(eff_lat, 6), "lon": round(eff_lon, 6),
            "coords_orientacyjne": False,          # współrzędne z geoportalu — PEWNE
            "confirmed": True,
            "parcel_source": f"ogłoszenie+ULDK ({via})",
            "srid": 2180,
        }
        nums = parcel["parcel_no"]
        notes.append(f"Numer działki z ogłoszenia rozwiązany w ULDK ({nums}, {via}) — POZYCJA z geoportalu, "
                     f"nie ze współrzędnych ogłoszenia. Współrzędne pewne.")
        # sygnał: rozwiązano w innym obrębie niż wskazywały współrzędne (typowe, gdy w ofercie adres agencji)
        if admin.get("region") and parcel["region"] and admin["region"] != parcel["region"]:
            notes.append(f"Działka leży w obrębie „{parcel['region']}”, a współrzędne z ogłoszenia trafiały "
                         f"w obręb „{admin['region']}” — numer działki miał pierwszeństwo.")
        if offer_area and area_total and abs(area_total - offer_area) / offer_area > 0.2:
            notes.append(f"Uwaga: suma pól z geometrii ({area_total} m²) różni się od powierzchni z oferty "
                         f"({round(offer_area)} m²) — sprawdź, czy numery obejmują całą ofertę.")
    else:
        # Brak rozwiązanego numeru — dotychczasowa logika: współrzędne ORIENTACYJNE, potwierdzenie po polu.
        parcel = by_xy
        if "error" not in parcel:
            parcel["coords_orientacyjne"] = True
            geom = parcel.get("area_m2_geom")
            parcel["area_m2_offer"] = round(offer_area) if offer_area else None
            if offer_area and geom:
                parcel["area_match"] = abs(geom - offer_area) / offer_area <= 0.15
            else:
                parcel["area_match"] = None
            parcel["confirmed_by_area"] = parcel["area_match"] is True
            if parcel["area_match"] is False:
                notes.append(f"Działka NIEpotwierdzona: pole z geometrii ({geom} m²) ≠ powierzchnia z oferty "
                             f"({round(offer_area)} m²) — punkt z ogłoszenia trafił w inną parcelę. "
                             f"Nie używaj nr działki bez weryfikacji (wskaż punkt na mapie / nr z ogłoszenia).")
            elif parcel["area_match"] is None:
                notes.append("Brak powierzchni do porównania — działka niepotwierdzona; nr tylko jeśli wprost w ogłoszeniu.")
        centroid = parcel.get("centroid_2180") if isinstance(parcel, dict) else None

    if not centroid:  # fallback: przelicz punkt wejściowy WGS84 -> PL-1992
        cx, cy = wgs84_to_pl1992(eff_lat, eff_lon)
        centroid = [round(cx, 2), round(cy, 2)]
        if not resolved:
            notes.append("NMT liczone z punktu ogłoszenia (brak geometrii działki z ULDK).")
    terrain = fetch_terrain(centroid)
    if "error" in terrain:
        notes.append(terrain["error"])
    pois = {} if skip_pois else fetch_pois(eff_lat, eff_lon, radius)
    for cat, val in pois.items():
        if isinstance(val, dict) and "error" in val:
            notes.append(val["error"])
    # UCIĄŻLIWOŚCI — osobno i w małym promieniu; to jest sprawdzenie rzeczy, o których ogłoszenie milczy
    nuisances = {} if skip_pois else fetch_nuisances(eff_lat, eff_lon, nuisance_radius)
    if isinstance(nuisances, dict) and "error" in nuisances:
        notes.append(nuisances["error"])
    else:
        notes.extend(nuisance_notes(nuisances))
    notes.append("Przeznaczenie (MPZP/WZ), transakcje (RCiWN) i właściciel (KW) — brak otwartego API; "
                 "patrz links.mpzp_hint / rcwin_hint / ekw_hint (weryfikacja ręczna).")
    links = build_links(eff_lat, eff_lon, parcel)
    # Google Maps do sekcji danych ewidencyjnych — zawsze, gdy mamy współrzędne (rozwiązane lub orientacyjne).
    if isinstance(parcel, dict):
        parcel["gmaps_url"] = f"https://www.google.com/maps?q={eff_lat},{eff_lon}"
    return {
        "input": {"lat": lat, "lon": lon, "radius_m": radius,
                  "position_lat": eff_lat, "position_lon": eff_lon,
                  "position_from": "geoportal (nr działki)" if resolved else "ogłoszenie (orientacyjne)"},
        "parcel": parcel,
        "terrain": terrain,
        "pois": pois,
        "nuisances": nuisances,
        "links": links,
        "notes": notes,
    }


def _coords_from_id(listing_id: str) -> tuple[float, float, float | None, list[str]]:
    import manage_listing
    fm, _ = manage_listing.load_listing(listing_id)
    lat, lon = fm.get("lat"), fm.get("lon")
    if lat is None or lon is None:
        raise SystemExit(f"Brak współrzędnych w {listing_id} — uzupełnij lat/lon lub podaj --lat/--lon")
    area = fm.get("area_m2")
    # kandydaci nazw obrębu z pliku (fallback, gdy skill nie poda --region-name): miejscowość, region, wcześniej ustalony obręb
    loc = fm.get("location") or {}
    names: list[str] = []
    for v in (loc.get("city"), loc.get("region"), (fm.get("parcel") or {}).get("region")):
        if v and str(v).strip() and str(v).strip() not in names:
            names.append(str(v).strip())
    return float(lat), float(lon), (float(area) if area else None), names


def main(argv: list[str] | None = None) -> int:
    common.setup_utf8()
    p = argparse.ArgumentParser(description="Pogłębiona analiza terenowa działki (ULDK+NMT+OSM).")
    p.add_argument("--id", help="ID listingu (pobierze lat/lon z pliku)")
    p.add_argument("--lat", type=float)
    p.add_argument("--lon", type=float)
    p.add_argument("--radius", type=int, default=15000, help="promień szukania POI/udogodnień (m)")
    p.add_argument("--nuisance-radius", dest="nuisance_radius", type=int, default=2500,
                   help="promień szukania uciążliwości: tory, drogi, cmentarz, ferma, przemysł (m)")
    p.add_argument("--skip-pois", action="store_true", help="pomiń Overpass (szybciej)")
    p.add_argument("--parcel-no", dest="parcel_no", action="append",
                   help="nr działki WPROST z ogłoszenia (powtarzalny) — rozwiązywany w ULDK na realne "
                        "współrzędne; to one określają pozycję, nie punkt z ogłoszenia")
    p.add_argument("--region-name", dest="region_name", action="append",
                   help="nazwa obrębu/miejscowości z ogłoszenia (powtarzalny) — użyta do rozwiązania nr działki "
                        "po nazwie (GetParcelByIdOrNr); ma pierwszeństwo nad obrębem spod współrzędnych")
    args = p.parse_args(argv)

    offer_area = None
    region_names = list(args.region_name or [])
    if args.id:
        lat, lon, offer_area, id_names = _coords_from_id(args.id)
        for n in id_names:                       # nazwy z pliku jako fallback (po tych podanych jawnie)
            if n not in region_names:
                region_names.append(n)
    elif args.lat is not None and args.lon is not None:
        lat, lon = args.lat, args.lon
    else:
        p.error("podaj --id albo --lat i --lon")

    result = analyze(lat, lon, radius=args.radius, skip_pois=args.skip_pois, offer_area=offer_area,
                     nuisance_radius=args.nuisance_radius,
                     parcel_nos=args.parcel_no, region_names=region_names)
    if args.id:
        result["id"] = args.id
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
