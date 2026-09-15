"""
scrape_facebook.py — DETERMINISTYCZNY czytnik nowych postów z grup ogłoszeniowych Facebooka.

Rola w pipelinie: odpowiednik etapu „listing" portali, ale grupy FB nie mają filtrów i mieszają ogłoszenia
z całej Polski, a posty to wolny tekst. Dlatego ten skrypt TYLKO CZYTA nowe posty (deterministycznie), a
wstępne dopasowanie (wyciągnięcie lokalizacji/pow./ceny + odsiew pudeł) robi agent LLM w skillu
properties-search (Krok 1b). „Nowe" = posty, których ID nie ma w seen_post_ids danej grupy (fb_groups.py).

Sesja: trwały profil Playwright (scripts/.fb_profile/) — jednorazowe logowanie `--login`, potem skany
korzystają z zapisanych ciasteczek. Profil zawiera aktywną sesję FB → jest w .gitignore, nie commitujemy.

Tryby:
  python scrape_facebook.py --login                       # jednorazowe logowanie w oknie
  python scrape_facebook.py --add-group <URL>             # rejestracja grupy (rozwiązuje link → id)
  python scrape_facebook.py --scan --group <id> [--max-posts 40] [--since-days 30] [--headed]
  python scrape_facebook.py --scan --all   [--max-posts 40] [--headed]
  python scrape_facebook.py --commit --group <id> --scanned-ids-file ids.json [--newest-ts "..."]

Wyjście --scan --group: {"meta": {..., "scanned_ids": [...]}, "listings": [<record source=facebook>, ...]}
Wyjście --scan --all:   [ {grupowy wynik jak wyżej}, ... ]
Czytanie jest BEZSTANOWE — znacznik przesuwa dopiero --commit (po przetworzeniu wsadu przez agenta).

UWAGA (kruchość): selektory DOM FB bywają zmienne; przy błędzie sesji/zerze postów skrypt zwraca
meta.error i nie wywala całego wyszukiwania. Niezawodność „tylko nowe" opieramy na dedup (seen_post_ids),
nie na kruchym parsowaniu dat.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys

import common
import fb_groups

PROFILE_DIR = os.path.join(common.SCRIPTS_DIR, ".fb_profile")

# JS wyciągający posty z aktualnie wyrenderowanych artykułów grupy.
# Zwraca tylko elementy z permalinkiem postu grupy (odsiewa komentarze i obce karty).
_EXTRACT_JS = r"""
() => {
  const origin = location.origin;
  const out = [];
  const seen = new Set();
  for (const a of document.querySelectorAll('div[role="article"]')) {
    let href = null;
    for (const link of a.querySelectorAll('a[href]')) {
      const h = link.getAttribute('href') || '';
      if (/\/(posts|permalink)\//.test(h) || /multi_permalinks=/.test(h)) { href = h; break; }
    }
    if (!href) continue;
    let abs;
    try { abs = new URL(href, origin).href; } catch (e) { continue; }
    let m = abs.match(/(?:posts|permalink)\/([A-Za-z0-9]+)/);
    if (!m) { const mm = abs.match(/multi_permalinks=([0-9]+)/); if (mm) m = mm; }
    if (!m) continue;
    const postId = m[1];
    if (seen.has(postId)) continue;
    seen.add(postId);
    const text = (a.innerText || '').trim();
    const images = [];
    for (const img of a.querySelectorAll('img')) {
      const src = img.currentSrc || img.src || '';
      if (src && /(scontent|fbcdn)/.test(src) && img.naturalWidth > 200) images.push(src);
    }
    // czas: spróbuj aria-label linku z czasem albo atrybut title
    let timeText = null;
    const tnode = a.querySelector('a[aria-label]');
    if (tnode) timeText = tnode.getAttribute('aria-label');
    out.push({ postId, url: abs.split('?')[0], text, images, timeText });
  }
  return out;
}
"""


def _now_ts() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


# Facebook agresywnie wykrywa automatyzację i odpowiada NIEKOŃCZĄCĄ SIĘ captchą. Trzy rzeczy, które
# o tym decydują (wszystkie obsłużone niżej):
#  1. Chromium z Playwrighta ma inny odcisk niż zwykły Chrome → używamy PRAWDZIWEGO Chrome (channel),
#     a na Chromium schodzimy dopiero, gdy Chrome'a nie ma w systemie;
#  2. podmiana user-agenta na sztywną wartość rozjeżdżała się z realnym systemem (UA "Windows, Chrome 124"
#     na macOS z Chrome 152 to jawny sygnał bota) → przy prawdziwym Chrome NIE nadpisujemy UA;
#  3. flaga AutomationControlled i `navigator.webdriver` → wyłączone / usunięte.
def _open_context(pw, headless: bool):
    """Trwały kontekst Playwright z profilem FB (zapamiętane logowanie)."""
    os.makedirs(PROFILE_DIR, exist_ok=True)
    opts = dict(
        headless=headless,
        locale="pl-PL",
        viewport={"width": 1366, "height": 900},
        args=["--disable-blink-features=AutomationControlled"],
    )
    ctx = None
    try:
        ctx = pw.chromium.launch_persistent_context(PROFILE_DIR, channel="chrome", **opts)
    except Exception:
        # brak zainstalowanego Chrome — fallback na Chromium (wtedy UA musi być spójny z platformą)
        ctx = pw.chromium.launch_persistent_context(PROFILE_DIR, user_agent=common.UA, **opts)
    try:
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
    except Exception:  # noqa: BLE001
        pass
    return ctx


def _logged_in(context) -> bool:
    try:
        return any(c.get("name") == "c_user" for c in context.cookies())
    except Exception:
        return False


# --- logowanie ------------------------------------------------------------
def do_login(timeout_s: int = 300) -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return {"ok": False, "error": "Playwright niedostępny — pip install playwright; python -m playwright install chromium"}
    with sync_playwright() as pw:
        context = _open_context(pw, headless=False)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://www.facebook.com/", wait_until="domcontentloaded")
        sys.stderr.write("[fb] Zaloguj się w otwartym oknie. Czekam na sesję (max %ds)...\n" % timeout_s)
        waited = 0
        while waited < timeout_s and not _logged_in(context):
            page.wait_for_timeout(2000)
            waited += 2
        ok = _logged_in(context)
        context.close()
        return {"ok": ok, "error": None if ok else "nie wykryto logowania (brak ciasteczka c_user)"}


# --- rejestracja grupy ----------------------------------------------------
def _group_id_from_url(url: str) -> str | None:
    m = re.search(r"/groups/(\d+)", url)
    return m.group(1) if m else None


def resolve_group(url: str) -> dict:
    """Rozwiąż link grupy (także share/g/<token>) na numeryczne id + nazwę. Używa zalogowanego profilu."""
    gid = _group_id_from_url(url)
    name = None
    # najpierw tania próba HTTP (część linków przekierowuje bez logowania)
    if not gid:
        try:
            r = common.http_get(url, accept="text/html")
            final = str(r.url)
            gid = _group_id_from_url(final)
            if not gid:
                m = re.search(r'"groupID":"(\d+)"', r.text) or re.search(r'/groups/(\d+)', r.text)
                gid = m.group(1) if m else None
        except Exception:
            pass
    # fallback: zalogowany Playwright (prywatne grupy / share-linki wymagające sesji)
    if not gid:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                context = _open_context(pw, headless=True)
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(3000)
                final = page.url
                gid = _group_id_from_url(final)
                if not gid:
                    html = page.content()
                    m = re.search(r'"groupID":"(\d+)"', html) or re.search(r'/groups/(\d+)', html)
                    gid = m.group(1) if m else None
                try:
                    name = page.title().replace(" | Facebook", "").strip() or None
                except Exception:
                    name = None
                context.close()
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"nie udało się rozwiązać linku: {exc}", "url": url}
    if not gid:
        return {"ok": False, "error": "nie znaleziono numerycznego id grupy w linku", "url": url}
    canonical = f"https://www.facebook.com/groups/{gid}"
    entry = fb_groups.add_group(canonical, gid, name)
    return {"ok": True, "id": gid, "url": canonical, "name": entry.get("name"), "added": entry.get("added")}


# --- skan -----------------------------------------------------------------
def _record_from_post(post: dict, group_id: str, group_name: str | None) -> dict:
    text = post.get("text") or ""
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    rec = common.empty_record()
    rec["source"] = "facebook"
    rec["source_id"] = f"{group_id}_{post['postId']}"
    rec["url"] = post.get("url")
    rec["title"] = (first[:90] or "Post FB")
    rec["kind"] = "dzialka"        # domyślnie; agent doprecyzuje (dzialka/dom)
    rec["transaction"] = "sale"
    rec["owner_type"] = "private"  # grupy ogłoszeniowe ≈ prywatne; agent może zmienić
    rec["description"] = text
    rec["images"] = (post.get("images") or [])[:8]
    rec["coords_approx"] = True
    rec["raw"] = {
        "group_id": str(group_id),
        "group_name": group_name,
        "post_id": post["postId"],
        "time_text": post.get("timeText"),
    }
    return rec


def scan_group(group_id: str, max_posts: int = 40, headed: bool = False) -> dict:
    """Zwróć {meta, listings} — NOWE posty grupy (ID spoza seen_post_ids). Stanu NIE rusza."""
    g = fb_groups.get_group(group_id)
    if not g:
        return {"meta": {"group_id": str(group_id), "error": "grupa nie zarejestrowana (--add-group)"},
                "listings": []}
    seen = set(map(str, g.get("seen_post_ids") or []))
    name = g.get("name")
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return {"meta": {"group_id": str(group_id), "name": name,
                         "error": "Playwright niedostępny"}, "listings": []}

    collected: dict[str, dict] = {}
    scanned_ids: list[str] = []
    error = None
    with sync_playwright() as pw:
        context = _open_context(pw, headless=not headed)
        page = context.pages[0] if context.pages else context.new_page()
        if not _logged_in(context):
            context.close()
            return {"meta": {"group_id": str(group_id), "name": name,
                             "error": "sesja wygasła — uruchom: scrape_facebook.py --login"},
                    "listings": []}
        url = f"https://www.facebook.com/groups/{group_id}/?sorting_setting=CHRONOLOGICAL"
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(3500)
            if "login" in page.url or "/checkpoint" in page.url:
                context.close()
                return {"meta": {"group_id": str(group_id), "name": name,
                                 "error": "przekierowano do logowania/checkpoint — uruchom --login"},
                        "listings": []}
            max_scrolls = min(60, max_posts + 12)
            stagnant = 0
            for _ in range(max_scrolls):
                try:
                    posts = page.evaluate(_EXTRACT_JS)
                except Exception as exc:  # noqa: BLE001
                    error = f"parsowanie DOM nieudane: {exc}"
                    break
                before = len(collected)
                for p in posts:
                    pid = str(p.get("postId"))
                    if pid not in scanned_ids:
                        scanned_ids.append(pid)
                    if pid in seen or pid in collected:
                        continue
                    collected[pid] = _record_from_post(p, group_id, name)
                if len(collected) >= max_posts:
                    break
                stagnant = stagnant + 1 if len(collected) == before else 0
                if stagnant >= 4:
                    break
                page.evaluate("window.scrollBy(0, 3000)")
                page.wait_for_timeout(2000)
        except Exception as exc:  # noqa: BLE001
            error = f"skan nieudany: {exc}"
        finally:
            context.close()

    listings = list(collected.values())[:max_posts]
    # Facebook DŁAWI zautomatyzowane przeglądarki: nawet przy poprawnej sesji i członkostwie w grupie
    # renderuje ~1-3 posty i nie doładowuje kolejnych (feed jest wirtualizowany, `scrollY` dobija do
    # końca strony po jednym ekranie). Trzeba to odróżnić od "grupa nie ma nowych postów", bo inaczej
    # pusty wynik wygląda na sukces. mbasic.facebook.com (kiedyś czysty HTML) został wycofany.
    throttled = len(scanned_ids) <= 3
    meta = {
        "source": "facebook",
        "group_id": str(group_id),
        "name": name,
        "in": len(scanned_ids),
        "returned": len(listings),
        "throttled": throttled,
        "scanned_ids": scanned_ids,
        "note": ("FB dławi zautomatyzowaną przeglądarkę — zobaczono tylko %d postów; to NIE znaczy, "
                 "że grupa nie ma nowych treści" % len(scanned_ids)) if throttled else None,
        "new_watermark": _now_ts(),
    }
    if error:
        meta["error"] = error
    return {"meta": meta, "listings": listings}


# --- commit ---------------------------------------------------------------
def commit(group_id: str, scanned_ids: list[str], newest_ts: str | None) -> dict:
    g = fb_groups.mark_scanned(group_id, scanned_ids, newest_ts or _now_ts())
    return {"ok": True, "group_id": str(group_id),
            "seen_total": len(g.get("seen_post_ids") or []),
            "last_post_ts": g.get("last_post_ts"), "last_scanned": g.get("last_scanned")}


# --- CLI ------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    common.setup_utf8()
    p = argparse.ArgumentParser(description="Czytnik nowych postów z grup Facebooka (deterministyczny).")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--login", action="store_true", help="jednorazowe logowanie w oknie")
    mode.add_argument("--add-group", dest="add_group", metavar="URL", help="zarejestruj grupę z linku")
    mode.add_argument("--scan", action="store_true", help="czytaj nowe posty grup(y)")
    mode.add_argument("--commit", action="store_true", help="przesuń znacznik po przetworzeniu wsadu")
    grp = p.add_mutually_exclusive_group(required=False)
    grp.add_argument("--group", help="numeryczne id grupy")
    grp.add_argument("--all", action="store_true", help="wszystkie włączone grupy")
    p.add_argument("--max-posts", dest="max_posts", type=int, default=40)
    p.add_argument("--since-days", dest="since_days", type=int, default=30)  # ograniczenie 1. skanu (informacyjne)
    p.add_argument("--headed", action="store_true", help="okno widoczne (fallback gdy headless blokowany)")
    p.add_argument("--scanned-ids-file", dest="scanned_ids_file")
    p.add_argument("--newest-ts", dest="newest_ts")
    args = p.parse_args(argv)

    if args.login:
        print(json.dumps(do_login(), ensure_ascii=False, indent=2))
        return 0

    if args.add_group:
        res = resolve_group(args.add_group)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res.get("ok") else 1

    if args.commit:
        if not args.group:
            p.error("--commit wymaga --group")
        ids = []
        if args.scanned_ids_file:
            with open(args.scanned_ids_file, encoding="utf-8") as fh:
                data = json.load(fh)
            ids = data.get("scanned_ids", data) if isinstance(data, dict) else data
        print(json.dumps(commit(args.group, ids, args.newest_ts), ensure_ascii=False, indent=2))
        return 0

    # --scan
    if args.all:
        groups = fb_groups.enabled_groups()
        results = [scan_group(g["id"], args.max_posts, args.headed) for g in groups]
        sys.stdout.write(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
        return 0
    if not args.group:
        p.error("--scan wymaga --group lub --all")
    res = scan_group(args.group, args.max_posts, args.headed)
    sys.stdout.write(json.dumps(res, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
