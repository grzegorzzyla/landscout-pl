"""
fb_groups.py — rejestr grup Facebooka i znaczniki „ostatnio przeczytane" (stan skanowania).

Jedno źródło prawdy: properties/facebook_groups.json. Każda grupa pamięta:
- url + numeryczne id (rozwiązane z linku udostępniania),
- last_post_ts — data najnowszego widzianego postu (watermark: granica scrollowania przy skanie),
- last_scanned — czas ostatniego udanego skanu,
- seen_post_ids — ID przetworzonych postów (także ODRZUCONYCH przez agenta), aby ich nie oceniać w kółko;
  posty FB odrzucone we wstępnym dopasowaniu nie trafiają do listings/ ani deleted/, więc dedup po
  (source, source_id) z manage_listing tu nie wystarcza.

Czytanie nowych postów jest bezstanowe (scrape_facebook.py --scan nie rusza stanu); znacznik przesuwa się
dopiero przez mark_scanned() (scrape_facebook.py --commit), po przetworzeniu wsadu przez agenta.

API (importowane przez scrape_facebook.py):
  load(), save(state), add_group(url, group_id, name=None), get_group(group_id),
  enabled_groups(), mark_scanned(group_id, scanned_ids, newest_ts)
"""
from __future__ import annotations

import datetime
import json
import os
from typing import Any

import common

STATE_PATH = os.path.join(common.PROJECT_DIR, "properties", "facebook_groups.json")

SEEN_CAP = 500  # ile ostatnich ID postów trzymać per grupa (zapobiega puchnięciu pliku)


def _now_ts() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def load() -> dict[str, Any]:
    try:
        with open(STATE_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        data = {}
    except Exception:
        data = {}
    data.setdefault("groups", [])
    return data


def save(state: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def get_group(group_id: str) -> dict[str, Any] | None:
    for g in load().get("groups", []):
        if str(g.get("id")) == str(group_id):
            return g
    return None


def enabled_groups() -> list[dict[str, Any]]:
    return [g for g in load().get("groups", []) if g.get("enabled", True)]


def add_group(url: str, group_id: str, name: str | None = None) -> dict[str, Any]:
    """Zarejestruj grupę (lub zaktualizuj url/name istniejącej). Zwraca wpis grupy."""
    state = load()
    for g in state["groups"]:
        if str(g.get("id")) == str(group_id):
            g["url"] = url or g.get("url")
            if name:
                g["name"] = name
            g.setdefault("enabled", True)
            save(state)
            return g
    entry = {
        "id": str(group_id),
        "url": url,
        "name": name,
        "enabled": True,
        "added": _now_ts(),
        "last_scanned": None,
        "last_post_ts": None,   # watermark — pierwszy skan ograniczany przez --since-days
        "seen_post_ids": [],
    }
    state["groups"].append(entry)
    save(state)
    return entry


def mark_scanned(group_id: str, scanned_ids: list[str], newest_ts: str | None = None) -> dict[str, Any]:
    """Po przetworzeniu wsadu: dopisz zeskanowane ID do seen_post_ids, przesuń watermark i last_scanned."""
    state = load()
    for g in state["groups"]:
        if str(g.get("id")) == str(group_id):
            seen = list(g.get("seen_post_ids") or [])
            have = set(map(str, seen))
            for pid in scanned_ids:
                if str(pid) not in have:
                    seen.append(str(pid))
                    have.add(str(pid))
            g["seen_post_ids"] = seen[-SEEN_CAP:]
            if newest_ts and (not g.get("last_post_ts") or newest_ts > g["last_post_ts"]):
                g["last_post_ts"] = newest_ts
            g["last_scanned"] = _now_ts()
            save(state)
            return g
    raise ValueError(f"Nie znaleziono grupy {group_id} w {STATE_PATH}")
