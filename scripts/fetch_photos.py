"""
fetch_photos.py — pobierz zdjęcia ogłoszenia z URL-i (frontmatter images[]) do
properties/photos/{id}/ i zarejestruj je w polu photos[].

Użycie:
  python fetch_photos.py --id 20260628_001 [--max 12]
  python fetch_photos.py --id 20260628_001 --url https://... --url https://...

Pobiera z listy `images` w pliku ogłoszenia (chyba że podano --url).
Pomija pobranie, jeśli liczba już zarejestrowanych zdjęć >= --max.
"""
from __future__ import annotations

import argparse
import os
import sys

import common
import manage_listing as ml


def _ext_from(url: str, content_type: str | None) -> str:
    for cand in (".jpg", ".jpeg", ".png", ".webp"):
        if cand in url.lower():
            return cand
    if content_type:
        if "png" in content_type:
            return ".png"
        if "webp" in content_type:
            return ".webp"
    return ".jpg"


def fetch(listing_id: str, urls: list[str] | None, max_count: int) -> list[str]:
    fm, body = ml.load_listing(listing_id)
    sources = urls if urls else list(fm.get("images") or [])
    dest_dir = os.path.join(ml.PHOTOS_DIR, listing_id)
    os.makedirs(dest_dir, exist_ok=True)
    photos = list(fm.get("photos") or [])
    added: list[str] = []

    for url in sources:
        if len(photos) >= max_count:
            break
        try:
            resp = common.http_get(url, accept="image/*")
            if resp.status_code != 200 or not resp.content:
                sys.stderr.write(f"[foto] pominięto {url} (status {resp.status_code})\n")
                continue
            ext = _ext_from(url, resp.headers.get("content-type"))
            name = f"{len(photos) + 1:02d}{ext}"
            with open(os.path.join(dest_dir, name), "wb") as fh:
                fh.write(resp.content)
            rel = f"photos/{listing_id}/{name}"
            photos.append(rel)
            added.append(rel)
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"[foto] błąd {url}: {exc}\n")

    fm["photos"] = photos
    fm["date_updated"] = ml._today()
    ml.save_listing(listing_id, fm, body)
    return added


def main(argv: list[str] | None = None) -> int:
    common.setup_utf8()
    p = argparse.ArgumentParser(description="Pobierz zdjęcia ogłoszenia.")
    p.add_argument("--id", required=True)
    p.add_argument("--url", action="append", default=None, help="Konkretny URL (powtarzalny)")
    p.add_argument("--max", type=int, default=12, help="Maks. liczba zdjęć łącznie")
    args = p.parse_args(argv)
    added = fetch(args.id, args.url, args.max)
    import json
    print(json.dumps({"id": args.id, "downloaded": added, "count": len(added)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
