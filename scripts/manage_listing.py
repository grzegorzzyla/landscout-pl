"""
manage_listing.py — bezpieczne zarządzanie plikami ogłoszeń properties/listings/*.md.

Gwarantuje integralność: frontmatter YAML jest mergowany (pola scraperowe odświeżane,
pola użytkownika zachowane), a sekcje treści (## Ocena dopasowania, ## Historia, ## Analiza pogłębiona)
nigdy nie są nadpisywane — tylko dopisywane. Notatki żyją we frontmatterze (notes[]), nie w treści.

ID pliku = YYYYMMDD_NNN (data dodania + numer kolejny), więc lista sortuje się po dacie.
Deduplikacja po (source, source_id): ponowny upsert tej samej oferty aktualizuje istniejący plik.

Subkomendy:
  upsert       --json-file F | --stdin   [--source-type listing|geoportal] [--status S] [--score N]
  note         --id ID --text "..."
  set-status   --id ID --status active|inactive|watch|favorite
  set          --id ID --field contact.phone --value "..."   (wartość parsowana jako JSON, potem string)
  set-tags     --id ID --tags "las,widok,cisza"   (zastępuje całą listę tagów; pusto = wyczyść)
  set-section  --id ID --header "Analiza pogłębiona" (--text "..." | --text-file F | stdin)
  add-photo    --id ID --file PLIK [--file PLIK ...]
  list         [--status S] [--json]
  get          --id ID

Biblioteka (importowana m.in. przez fetch_photos.py): load_listing, save_listing,
find_by_source, list_ids.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import sys
import time
from typing import Any

import yaml

import common

LISTINGS_DIR = os.path.join(common.PROJECT_DIR, "properties", "listings")
DELETED_DIR = os.path.join(LISTINGS_DIR, "deleted")  # oferty SKASOWANE — poza listą/stroną, ale brane do dedup
PHOTOS_DIR = os.path.join(common.PROJECT_DIR, "properties", "photos")

ID_RE = re.compile(r"^\d{8}_\d{3,}$")  # data_NNN; NNN globalnie unikalny (≥3 cyfry, może urosnąć)

# pola odświeżane z danych scrapera przy upsert
SCRAPER_FIELDS = [
    "source", "source_id", "url", "title", "kind", "price", "price_per_m2", "area_m2",
    "transaction", "plot_type", "location", "lat", "lon", "coords_approx",
    "owner_type", "description", "date_created",
]

# kanoniczna kolejność kluczy frontmattera przy zapisie
KEY_ORDER = [
    "id", "source", "source_id", "source_type", "added_by", "url", "status", "score", "seen", "seen_at",
    "title", "kind", "price", "price_per_m2", "area_m2", "land_type", "transaction", "plot_type",
    "location", "lat", "lon", "coords_approx", "owner_type",
    "contact", "mpzp", "media", "notes", "tags", "parcel", "terrain", "deep_dive",
    "images", "photos", "cover", "map_photo",
    "date_created", "date_added", "date_updated",
]

DEFAULT_USER_FIELDS: dict[str, Any] = {
    "contact": {"name": None, "phone": None, "email": None},
    "mpzp": {"status": None, "link": None, "note": None},
    "media": {"prad": None, "woda": None, "kanalizacja": None, "gaz": None},
}


def _ymd() -> str:
    """Kompaktowa data do ID pliku (YYYYMMDD)."""
    return datetime.date.today().strftime("%Y%m%d")


def _today() -> str:
    """Data ISO (YYYY-MM-DD) do pól i wpisów historii/notatek."""
    return datetime.date.today().strftime("%Y-%m-%d")


def _ensure_dirs() -> None:
    os.makedirs(LISTINGS_DIR, exist_ok=True)
    os.makedirs(PHOTOS_DIR, exist_ok=True)


def _path(listing_id: str) -> str:
    return os.path.join(LISTINGS_DIR, f"{listing_id}.md")


def list_ids() -> list[str]:
    if not os.path.isdir(LISTINGS_DIR):
        return []
    ids = [f[:-3] for f in os.listdir(LISTINGS_DIR) if f.endswith(".md") and ID_RE.match(f[:-3])]
    return sorted(ids)


def load_listing(listing_id: str) -> tuple[dict, str]:
    """Zwróć (frontmatter, body). Rzuca FileNotFoundError jeśli brak."""
    with open(_path(listing_id), encoding="utf-8") as fh:
        text = fh.read()
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    if not m:
        return {}, text
    fm = yaml.safe_load(m.group(1)) or {}
    return fm, m.group(2)


def _ordered_fm(fm: dict) -> dict:
    out: dict[str, Any] = {}
    for key in KEY_ORDER:
        if key in fm:
            out[key] = fm[key]
    for key, val in fm.items():  # dorzuć ewentualne nieznane klucze na końcu
        if key not in out:
            out[key] = val
    return out


def save_listing(listing_id: str, fm: dict, body: str) -> None:
    _ensure_dirs()
    dumped = yaml.safe_dump(_ordered_fm(fm), allow_unicode=True, sort_keys=False, default_flow_style=False)
    text = f"---\n{dumped}---\n{body.lstrip(chr(10))}"
    with open(_path(listing_id), "w", encoding="utf-8") as fh:
        fh.write(text)


def _norm_url(url: Any) -> str:
    """Znormalizuj URL do porównań dedup: bez protokołu/www, bez query/fragmentu, bez końcowego '/'.
    Stabilny klucz oferty tam, gdzie source_id bywa niestabilny (np. Otodom nadaje 2 różne ID)."""
    if not url or not isinstance(url, str):
        return ""
    u = url.strip().lower()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    u = u.split("?")[0].split("#")[0]
    return u.rstrip("/")


def find_by_source(source: str, source_id: str) -> str | None:
    for lid in list_ids():
        fm, _ = load_listing(lid)
        if str(fm.get("source")) == str(source) and str(fm.get("source_id")) == str(source_id):
            return lid
    return None


def find_by_url(url: str) -> str | None:
    """Znajdź ofertę w listings/ po znormalizowanym URL (dedup odporny na niestabilne source_id)."""
    target = _norm_url(url)
    if not target:
        return None
    for lid in list_ids():
        fm, _ = load_listing(lid)
        if _norm_url(fm.get("url")) == target:
            return lid
    return None


def _all_used_numbers() -> list[int]:
    """Numery (część po '_') ze WSZYSTKICH ofert: listings/ + deleted/ — by NNN był globalnie unikalny
    i nigdy nie był reużyty (też po skasowaniu)."""
    nums: list[int] = []
    for dir_ in (LISTINGS_DIR, DELETED_DIR):
        if not os.path.isdir(dir_):
            continue
        for f in os.listdir(dir_):
            if f.endswith(".md") and ID_RE.match(f[:-3]):
                nums.append(int(f[:-3].split("_")[1]))
    return nums


def _next_id() -> str:
    """Data = pomocnicza (data utworzenia); NNN = globalnie unikalny, monotoniczny numer oferty."""
    today = _ymd()
    nums = _all_used_numbers()
    return f"{today}_{(max(nums) + 1) if nums else 1:03d}"


# --- operacje na sekcjach treści -----------------------------------------
def _new_body(source: str, score: Any) -> str:
    # Notatki żyją w frontmatterze (notes[]), nie w treści — nie generuj tu sekcji ## Notatki.
    return (
        "## Ocena dopasowania\n\n"
        f"_Brak oceny._\n\n"
        "## Historia\n"
    )


def _tidy(body: str) -> str:
    """Zapewnij pustą linię przed każdym nagłówkiem sekcji i scal nadmiarowe puste linie."""
    body = re.sub(r"\n{3,}", "\n\n", body)
    body = re.sub(r"([^\n])\n(##\s)", r"\1\n\n\2", body)
    return body


def _append_to_section(body: str, header: str, line: str) -> str:
    """Dopisz `line` na końcu sekcji `## header`, zachowując resztę."""
    pattern = re.compile(rf"(^##\s+{re.escape(header)}\s*\n)(.*?)(?=^##\s|\Z)", re.S | re.M)
    m = pattern.search(body)
    if not m:
        # sekcja nie istnieje — dodaj na końcu
        return _tidy(body.rstrip() + f"\n\n## {header}\n\n{line}\n")
    block = m.group(2).rstrip("\n")
    new_block = (block + "\n" if block else "") + line + "\n\n"
    return _tidy(body[:m.start(2)] + new_block + body[m.end(2):])


def _set_section(body: str, header: str, content: str) -> str:
    pattern = re.compile(rf"(^##\s+{re.escape(header)}\s*\n)(.*?)(?=^##\s|\Z)", re.S | re.M)
    repl = lambda m: m.group(1) + "\n" + content.rstrip() + "\n\n"
    if pattern.search(body):
        return _tidy(pattern.sub(repl, body, count=1))
    return _tidy(body.rstrip() + f"\n\n## {header}\n\n{content.rstrip()}\n")


# --- upsert ---------------------------------------------------------------
def upsert_record(record: dict, source_type: str = "listing",
                  status: str | None = None, score: Any = None,
                  added_by: str | None = None) -> tuple[str, bool]:
    """Dodaj lub zaktualizuj ogłoszenie. Zwraca (id, created?)."""
    _ensure_dirs()
    source = record.get("source")
    source_id = record.get("source_id")
    # dedup: najpierw po (source, source_id), a gdy brak trafienia — po znormalizowanym URL
    # (source_id bywa niestabilny, np. Otodom; URL jest stabilnym kluczem oferty).
    existing = find_by_source(source, source_id) if source and source_id else None
    if not existing:
        existing = find_by_url(record.get("url"))
    created = existing is None
    listing_id = existing or _next_id()

    if existing:
        fm, body = load_listing(listing_id)
    else:
        fm = {"id": listing_id, "source_type": source_type, "added_by": added_by or "search",
              "status": status or "active", "score": score, "images": [], "photos": [],
              "date_added": _now_ts()}
        for key, val in DEFAULT_USER_FIELDS.items():
            fm[key] = json.loads(json.dumps(val))  # deep copy
        body = _new_body(source or "", score)

    # odśwież pola scraperowe
    for key in SCRAPER_FIELDS:
        if key in record and record[key] is not None:
            fm[key] = record[key]
    # obrazy ze źródła (URL) — zachowujemy listę do późniejszego pobrania
    if record.get("images"):
        fm["images"] = record["images"]
    if status is not None:
        fm["status"] = status
    if score is not None:
        fm["score"] = score
    # added_by = proweniencja (jak oferta weszła PIERWSZY raz) — nie nadpisuj przy aktualizacji
    if created and added_by is not None:
        fm["added_by"] = added_by
    fm.setdefault("source_type", source_type)
    fm.setdefault("added_by", "search")
    fm.setdefault("status", "active")
    fm.setdefault("photos", [])
    fm["id"] = listing_id
    fm["date_updated"] = _now_ts()

    # uzupełnij współrzędne, jeśli brak (np. Otodom)
    if not fm.get("lat") or not fm.get("lon"):
        loc = fm.get("location") or {}
        query = ", ".join([p for p in [loc.get("address"), loc.get("city"), loc.get("region"), "Polska"] if p])
        if query:
            coords = common.geocode(query)
            if coords:
                fm["lat"], fm["lon"] = coords
                fm["coords_approx"] = True

    # wpis do historii
    if created:
        msg = f"utworzono z {source}" + (f" (score {fm.get('score')})" if fm.get("score") is not None else "")
    else:
        msg = f"zaktualizowano z {source}" + (f" (score {fm.get('score')})" if score is not None else "")
    body = _append_to_section(body, "Historia", f"- {_today()} {msg}")

    save_listing(listing_id, fm, body)
    return listing_id, created


# --- pozostałe operacje ---------------------------------------------------
def _now_ts() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def note_add(listing_id: str, text: str) -> dict:
    """Dodaj notatkę (ustrukturyzowaną) do frontmattera. Zwraca utworzoną notatkę."""
    fm, body = load_listing(listing_id)
    notes = list(fm.get("notes") or [])
    note = {"id": str(int(time.time() * 1000)), "ts": _now_ts(), "text": text}
    notes.append(note)
    fm["notes"] = notes
    fm["date_updated"] = _now_ts()
    save_listing(listing_id, fm, body)
    return note


def note_edit(listing_id: str, note_id: str, text: str) -> dict:
    fm, body = load_listing(listing_id)
    notes = list(fm.get("notes") or [])
    for n in notes:
        if str(n.get("id")) == str(note_id):
            n["text"] = text
            n["ts"] = _now_ts() + " (edyt.)"
            break
    else:
        raise ValueError(f"Nie znaleziono notatki {note_id}")
    fm["notes"] = notes
    fm["date_updated"] = _now_ts()
    save_listing(listing_id, fm, body)
    return {"id": note_id}


def note_delete(listing_id: str, note_id: str) -> dict:
    fm, body = load_listing(listing_id)
    notes = [n for n in (fm.get("notes") or []) if str(n.get("id")) != str(note_id)]
    fm["notes"] = notes
    fm["date_updated"] = _now_ts()
    save_listing(listing_id, fm, body)
    return {"id": note_id, "deleted": True}


def _norm_tags(raw) -> list[str]:
    """Znormalizuj listę tagów: trim, usuń puste/przecinki, dedup (case-insensitive) z zachowaniem kolejności."""
    out: list[str] = []
    seen: set[str] = set()
    for t in (raw or []):
        s = str(t).replace(",", " ").strip()
        s = re.sub(r"\s+", " ", s)
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def set_tags(listing_id: str, tags: list[str]) -> list[str]:
    """Ustaw (zastąp) całą listę tagów oferty. Pusta lista usuwa pole tags."""
    fm, body = load_listing(listing_id)
    tags = _norm_tags(tags)
    if tags:
        fm["tags"] = tags
    else:
        fm.pop("tags", None)
    fm["date_updated"] = _now_ts()
    save_listing(listing_id, fm, body)
    return tags


def set_status(listing_id: str, status: str) -> None:
    fm, body = load_listing(listing_id)
    fm["status"] = status
    fm["date_updated"] = _now_ts()
    body = _append_to_section(body, "Historia", f"- {_today()} status → {status}")
    save_listing(listing_id, fm, body)


def set_field(listing_id: str, dotted: str, value: Any) -> None:
    fm, body = load_listing(listing_id)
    keys = dotted.split(".")
    node = fm
    for k in keys[:-1]:
        node = node.setdefault(k, {})
        if not isinstance(node, dict):
            raise ValueError(f"Pole '{dotted}' koliduje z wartością nie-słownikową.")
    node[keys[-1]] = value
    fm["date_updated"] = _now_ts()
    save_listing(listing_id, fm, body)


def add_photo_files(listing_id: str, files: list[str]) -> list[str]:
    fm, body = load_listing(listing_id)
    dest_dir = os.path.join(PHOTOS_DIR, listing_id)
    os.makedirs(dest_dir, exist_ok=True)
    photos = list(fm.get("photos") or [])
    existing_count = len(photos)
    added = []
    for i, src in enumerate(files):
        ext = os.path.splitext(src)[1] or ".jpg"
        name = f"{existing_count + i + 1:02d}{ext}"
        shutil.copy2(src, os.path.join(dest_dir, name))
        rel = f"photos/{listing_id}/{name}"
        photos.append(rel)
        added.append(rel)
    fm["photos"] = photos
    fm["date_updated"] = _now_ts()
    save_listing(listing_id, fm, body)
    return added


# --- CLI ------------------------------------------------------------------
def _read_record(args) -> dict:
    if args.stdin:
        return json.load(sys.stdin)
    with open(args.json_file, encoding="utf-8") as fh:
        return json.load(fh)


def _parse_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except Exception:
        return raw


def cmd_upsert(args) -> int:
    rec = _read_record(args)
    listing_id, created = upsert_record(
        rec, source_type=args.source_type, status=args.status, score=args.score,
        added_by=args.added_by,
    )
    print(json.dumps({"id": listing_id, "created": created}, ensure_ascii=False))
    return 0


def cmd_note(args) -> int:
    # Alias: notatki żyją we frontmatterze (notes[]) — kieruj do modelu ustrukturyzowanego.
    note = note_add(args.id, args.text)
    print(json.dumps({"id": args.id, "note": note}, ensure_ascii=False))
    return 0


def cmd_note_add(args) -> int:
    note = note_add(args.id, args.text)
    print(json.dumps({"id": args.id, "note": note}, ensure_ascii=False))
    return 0


def cmd_note_edit(args) -> int:
    note_edit(args.id, args.note_id, args.text)
    print(json.dumps({"id": args.id, "note_id": args.note_id, "edited": True}, ensure_ascii=False))
    return 0


def cmd_note_delete(args) -> int:
    note_delete(args.id, args.note_id)
    print(json.dumps({"id": args.id, "note_id": args.note_id, "deleted": True}, ensure_ascii=False))
    return 0


def cmd_set_status(args) -> int:
    set_status(args.id, args.status)
    print(json.dumps({"id": args.id, "status": args.status}, ensure_ascii=False))
    return 0


def delete_listing(listing_id: str) -> None:
    """Przenieś ofertę do listings/deleted/ (SKASOWANA). Usuwa zdjęcia (dedup używa tylko frontmattera).
    Przywrócenie tylko ręczne — przeniesienie pliku z powrotem do listings/."""
    src = _path(listing_id)
    if not os.path.exists(src):
        raise FileNotFoundError(f"Brak oferty {listing_id} w listings/")
    os.makedirs(DELETED_DIR, exist_ok=True)
    shutil.move(src, os.path.join(DELETED_DIR, f"{listing_id}.md"))
    ph = os.path.join(PHOTOS_DIR, listing_id)
    if os.path.isdir(ph):
        shutil.rmtree(ph, ignore_errors=True)


def _scan_keys(dir_: str, scope: str) -> list[dict]:
    out: list[dict] = []
    if not os.path.isdir(dir_):
        return out
    for f in os.listdir(dir_):
        if not (f.endswith(".md") and ID_RE.match(f[:-3])):
            continue
        try:
            with open(os.path.join(dir_, f), encoding="utf-8") as fh:
                m = re.match(r"^---\n(.*?)\n---", fh.read(), re.S)
            fm = yaml.safe_load(m.group(1)) if m else {}
        except Exception:
            fm = {}
        out.append({"id": f[:-3], "source": fm.get("source"),
                    "source_id": fm.get("source_id"), "url": _norm_url(fm.get("url")),
                    "scope": scope})
    return out


def known_keys() -> list[dict]:
    """Wszystkie oferty z listings/ ORAZ listings/deleted/ (source, source_id, znormalizowany url) —
    do dedup w wyszukiwaniu. Oferta raz skasowana/dodana nie wraca przez ingest, także gdy portal nada
    inny source_id (dedup łapie ją po URL)."""
    return _scan_keys(LISTINGS_DIR, "active") + _scan_keys(DELETED_DIR, "deleted")


_STATUS_RANK = {"favorite": 3, "watch": 2, "active": 1, "inactive": 0}


def _richness(fm: dict, listing_id: str) -> tuple:
    """Klucz „bogactwa" rekordu do wyboru, który z duplikatów zachować (większy = lepszy).
    Priorytet: status (ulubione/obserwowane najwyżej) → ma ocenę → liczba zdjęć → notatki → deep-dive;
    remis rozstrzyga niższe ID (starsza/kanoniczna oferta)."""
    num = int(listing_id.split("_")[1]) if "_" in listing_id else 0
    return (
        _STATUS_RANK.get(fm.get("status"), 0),
        1 if fm.get("score") is not None else 0,
        len(fm.get("photos") or []),
        1 if fm.get("notes") else 0,
        1 if fm.get("deep_dive") else 0,
        1 if (fm.get("parcel") or {}).get("confirmed") else 0,
        -num,  # remis → mniejszy numer (starsza oferta) wygrywa
    )


def find_duplicate_groups() -> tuple[list[list[str]], dict]:
    """Grupy ID (>1) uznane za tę samą ofertę: połączone po (source, source_id) LUB znormalizowanym URL.
    Zwraca (grupy, {id: frontmatter})."""
    ids = list_ids()
    meta: dict[str, dict] = {}
    parent = {i: i for i in ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    by_sid: dict[tuple, list[str]] = {}
    by_url: dict[str, list[str]] = {}
    for i in ids:
        fm, _ = load_listing(i)
        meta[i] = fm
        s, sid = fm.get("source"), fm.get("source_id")
        if s and sid not in (None, "None", ""):
            by_sid.setdefault((str(s), str(sid)), []).append(i)
        u = _norm_url(fm.get("url"))
        if u:
            by_url.setdefault(u, []).append(i)
    for grp in list(by_sid.values()) + list(by_url.values()):
        for j in grp[1:]:
            union(grp[0], j)
    comps: dict[str, list[str]] = {}
    for i in ids:
        comps.setdefault(find(i), []).append(i)
    return [sorted(v) for v in comps.values() if len(v) > 1], meta


def dedupe(apply: bool = False) -> list[dict]:
    """Wykryj duplikaty (po source_id/URL). Dla każdej grupy zostaw najbogatszy rekord, resztę przenieś
    do deleted/ (z wpisem do historii keepera). apply=False → tylko plan (dry-run)."""
    groups, meta = find_duplicate_groups()
    plan = []
    for grp in groups:
        keeper = max(grp, key=lambda i: _richness(meta[i], i))
        losers = [i for i in grp if i != keeper]
        plan.append({"keep": keeper, "delete": losers,
                     "source": meta[keeper].get("source"),
                     "url": _norm_url(meta[keeper].get("url"))})
        if apply:
            for i in losers:
                delete_listing(i)
            log_history(keeper, f"dedup: scalono duplikaty {', '.join(losers)} (skasowane)")
    return plan


def mark_seen(listing_id: str) -> None:
    """Oznacz ofertę jako obejrzaną (przy otwarciu karty). Nie zmienia date_updated."""
    fm, body = load_listing(listing_id)
    if not fm.get("seen"):
        fm["seen"] = True
        fm["seen_at"] = _now_ts()
        save_listing(listing_id, fm, body)


def cmd_seen(args) -> int:
    mark_seen(args.id)
    print(json.dumps({"id": args.id, "seen": True}, ensure_ascii=False))
    return 0


def cmd_delete(args) -> int:
    delete_listing(args.id)
    print(json.dumps({"id": args.id, "deleted": True}, ensure_ascii=False))
    return 0


def cmd_known(args) -> int:
    print(json.dumps(known_keys(), ensure_ascii=False, indent=2))
    return 0


def cmd_dedupe(args) -> int:
    plan = dedupe(apply=args.apply)
    print(json.dumps({"applied": args.apply, "groups": len(plan), "plan": plan},
                     ensure_ascii=False, indent=2))
    return 0


def log_history(listing_id: str, text: str) -> None:
    fm, body = load_listing(listing_id)
    body = _append_to_section(body, "Historia", f"- {_today()} {text}")
    fm["date_updated"] = _now_ts()
    save_listing(listing_id, fm, body)


def cmd_log(args) -> int:
    log_history(args.id, args.text)
    print(json.dumps({"id": args.id, "logged": True}, ensure_ascii=False))
    return 0


def cmd_set(args) -> int:
    set_field(args.id, args.field, _parse_value(args.value))
    print(json.dumps({"id": args.id, "field": args.field}, ensure_ascii=False))
    return 0


def cmd_set_tags(args) -> int:
    raw = args.tags.split(",") if args.tags else []
    tags = set_tags(args.id, raw)
    print(json.dumps({"id": args.id, "tags": tags}, ensure_ascii=False))
    return 0


def set_section(listing_id: str, header: str, content: str) -> None:
    """Zapisz/zastąp całą sekcję treści (np. 'Analiza pogłębiona')."""
    fm, body = load_listing(listing_id)
    body = _set_section(body, header, content)
    fm["date_updated"] = _now_ts()
    save_listing(listing_id, fm, body)


def cmd_set_section(args) -> int:
    if args.text is not None:
        content = args.text
    elif args.text_file:
        with open(args.text_file, encoding="utf-8") as fh:
            content = fh.read()
    else:
        content = sys.stdin.read()
    set_section(args.id, args.header, content)
    print(json.dumps({"id": args.id, "section": args.header}, ensure_ascii=False))
    return 0


def cmd_add_photo(args) -> int:
    added = add_photo_files(args.id, args.file)
    print(json.dumps({"id": args.id, "added": added}, ensure_ascii=False))
    return 0


def cmd_list(args) -> int:
    rows = []
    for lid in list_ids():
        fm, _ = load_listing(lid)
        if args.status and fm.get("status") != args.status:
            continue
        rows.append({k: fm.get(k) for k in
                     ["id", "status", "score", "title", "price", "area_m2",
                      "transaction", "source", "source_type", "added_by"]} | {"city": (fm.get("location") or {}).get("city")})
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for r in rows:
            print(f"{r['id']} | {r['status']:<8} | score {str(r['score']):>4} | "
                  f"{str(r['price']):>8} zł | {str(r['area_m2']):>6} m² | "
                  f"{(r['city'] or '')[:18]:<18} | {(r['title'] or '')[:40]}")
    return 0


def cmd_get(args) -> int:
    fm, body = load_listing(args.id)
    print(json.dumps({"frontmatter": fm, "body": body}, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Zarządzanie ogłoszeniami działek.")
    sub = p.add_subparsers(dest="cmd", required=True)

    up = sub.add_parser("upsert", help="Dodaj/aktualizuj ogłoszenie z rekordu JSON")
    src = up.add_mutually_exclusive_group(required=True)
    src.add_argument("--json-file", dest="json_file")
    src.add_argument("--stdin", action="store_true")
    up.add_argument("--source-type", choices=["listing", "geoportal"], default="listing")
    up.add_argument("--status", choices=["active", "inactive", "watch", "favorite"], default=None)
    up.add_argument("--score", type=int, default=None)
    up.add_argument("--added-by", dest="added_by", choices=["search", "user"], default=None,
                    help="tryb dodania: search (z wyszukiwania) | user (ręcznie ze strony)")
    up.set_defaults(func=cmd_upsert)

    nt = sub.add_parser("note", help="Dopisz notatkę")
    nt.add_argument("--id", required=True)
    nt.add_argument("--text", required=True)
    nt.set_defaults(func=cmd_note)

    ss = sub.add_parser("set-status", help="Ustaw status (active/inactive/watch/favorite)")
    ss.add_argument("--id", required=True)
    ss.add_argument("--status", required=True, choices=["active", "inactive", "watch", "favorite"])
    ss.set_defaults(func=cmd_set_status)

    na = sub.add_parser("note-add", help="Dodaj notatkę (ustrukturyzowaną, frontmatter notes[])")
    na.add_argument("--id", required=True)
    na.add_argument("--text", required=True)
    na.set_defaults(func=cmd_note_add)

    ne = sub.add_parser("note-edit", help="Edytuj notatkę po id")
    ne.add_argument("--id", required=True)
    ne.add_argument("--note-id", dest="note_id", required=True)
    ne.add_argument("--text", required=True)
    ne.set_defaults(func=cmd_note_edit)

    nde = sub.add_parser("note-delete", help="Usuń notatkę po id")
    nde.add_argument("--id", required=True)
    nde.add_argument("--note-id", dest="note_id", required=True)
    nde.set_defaults(func=cmd_note_delete)

    sn = sub.add_parser("seen", help="Oznacz ofertę jako obejrzaną")
    sn.add_argument("--id", required=True)
    sn.set_defaults(func=cmd_seen)

    dl = sub.add_parser("delete", help="Przenieś ofertę do listings/deleted (skasowana; przywrócenie ręczne)")
    dl.add_argument("--id", required=True)
    dl.set_defaults(func=cmd_delete)

    ks = sub.add_parser("known-sources", help="(source, source_id, url) z listings + deleted — do dedup")
    ks.set_defaults(func=cmd_known)

    dd = sub.add_parser("dedupe", help="Wykryj duplikaty (source_id/URL); zostaw najbogatszy, resztę do deleted")
    dd.add_argument("--apply", action="store_true", help="wykonaj (bez tego tylko plan/dry-run)")
    dd.set_defaults(func=cmd_dedupe)

    lg = sub.add_parser("log", help="Dopisz wpis do sekcji ## Historia")
    lg.add_argument("--id", required=True)
    lg.add_argument("--text", required=True)
    lg.set_defaults(func=cmd_log)

    st = sub.add_parser("set", help="Ustaw pole frontmattera (np. contact.phone)")
    st.add_argument("--id", required=True)
    st.add_argument("--field", required=True)
    st.add_argument("--value", required=True)
    st.set_defaults(func=cmd_set)

    tg = sub.add_parser("set-tags", help="Ustaw (zastąp) tagi oferty; --tags rozdzielane przecinkiem")
    tg.add_argument("--id", required=True)
    tg.add_argument("--tags", default="", help="lista tagów rozdzielana przecinkiem (pusto = wyczyść)")
    tg.set_defaults(func=cmd_set_tags)

    sec = sub.add_parser("set-section", help="Zapisz/zastąp sekcję treści (np. 'Analiza pogłębiona')")
    sec.add_argument("--id", required=True)
    sec.add_argument("--header", required=True)
    secsrc = sec.add_mutually_exclusive_group(required=False)
    secsrc.add_argument("--text")
    secsrc.add_argument("--text-file", dest="text_file")
    sec.set_defaults(func=cmd_set_section, text=None, text_file=None)

    ap = sub.add_parser("add-photo", help="Dodaj lokalne pliki zdjęć")
    ap.add_argument("--id", required=True)
    ap.add_argument("--file", action="append", required=True)
    ap.set_defaults(func=cmd_add_photo)

    ls = sub.add_parser("list", help="Wypisz ogłoszenia")
    ls.add_argument("--status", default=None)
    ls.add_argument("--json", action="store_true")
    ls.set_defaults(func=cmd_list)

    gt = sub.add_parser("get", help="Pokaż jedno ogłoszenie (JSON)")
    gt.add_argument("--id", required=True)
    gt.set_defaults(func=cmd_get)
    return p


def main(argv: list[str] | None = None) -> int:
    common.setup_utf8()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
