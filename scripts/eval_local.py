"""
eval_local.py — ocena ofert lokalnym modelem przez API zgodne z OpenAI (llama.cpp, Ollama, vLLM…).

PO CO: ocena to najdroższy element pipeline'u — przy kilkuset ofertach idą na nią miliony tokenów,
podczas gdy sama orkiestracja i deep-dive są tanie. Przeniesienie scoringu na lokalny model ścina
zużycie o rząd wielkości, a zadanie jest w zasięgu modelu 27–30B: klasyfikacja tekstu względem
opisu kryteriów, z krótkim wyjściem strukturalnym.

CZEGO NIE PRZENOSIMY: orkiestracji (wielokrokowe użycie narzędzi, radzenie sobie z błędami portali)
ani oględzin zdjęć — tam małe modele zawodzą, a deep-dive potrzebuje wizji.

KONTRAKT jest ten sam co skilla `properties-eval`, żeby oba były wymienne:
  wejście : lista pełnych rekordów ofert (jak z `manage_listing.py get`)
  wyjście : [{"id","source","source_id","score","verdict","reason","flags"}]
            verdict ∈ {"dopasowane","do-weryfikacji","odrzucone"}

UWAGA NA PORÓWNANIE: zanim przestawisz się na lokalny model na stałe, puść oba na tej samej partii
i porównaj werdykty (`--compare-with plik.json`). Ocena Claude wyłapywała rzeczy subtelne —
„sprzedający sam chwali się bliskością S19", „przystanek kolejowy we wsi", „cena wywoławcza
dwukrotnie wyższa niż w tej samej gminie". Jeśli lokalny model to gubi, oszczędność jest pozorna.

Użycie:
  python3 scripts/eval_local.py --records-file recs.json \
      [--url http://host:8080/v1] [--model qwen] [--batch-size 8] [--compare-with claude.json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

import httpx

import common

DEFAULT_URL = os.environ.get("LOCAL_LLM_URL", "http://127.0.0.1:8080/v1")
DEFAULT_MODEL = os.environ.get("LOCAL_LLM_MODEL", "local")
API_KEY = os.environ.get("LOCAL_LLM_KEY", "nie-wymagany")

VERDICTS = ("dopasowane", "do-weryfikacji", "odrzucone")

SYSTEM = (
    "Jesteś rzeczoznawcą oceniającym oferty gruntów względem kryteriów kupującego. "
    "Odpowiadasz WYŁĄCZNIE tablicą JSON, bez komentarza i bez bloków kodu. "
    "Każdy element: {\"id\":str,\"score\":int 0-100,\"verdict\":str,\"reason\":str,\"flags\":[str]}. "
    f"verdict musi być jedną z wartości: {', '.join(VERDICTS)}. "
    "reason: jedno–dwa zdania po polsku, z konkretem (powierzchnia w ha, cena za m², co przesądziło). "
    "Nie zgaduj na korzyść: gdy brakuje danych o wymaganiach krytycznych, obniż ocenę i daj "
    "verdict 'do-weryfikacji' zamiast 'dopasowane'."
)


def _criteria_text(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _slim(rec: dict) -> dict:
    """Do modelu idzie podzbiór pól — pełny rekord ma zdjęcia i surowe dane portalu,
    które tylko rozcieńczają kontekst i zżerają okno małego modelu."""
    fm = rec.get("frontmatter", rec)
    out = {
        "id": fm.get("id"),
        "source": fm.get("source"),
        "source_id": fm.get("source_id"),
        "title": fm.get("title"),
        "kind": fm.get("kind"),
        "area_m2": fm.get("area_m2"),
        "price": fm.get("price"),
        "price_per_m2": fm.get("price_per_m2"),
        "plot_type": fm.get("plot_type"),
        "land_type": fm.get("land_type"),
        "location": fm.get("location"),
        "owner_type": fm.get("owner_type"),
        "url": fm.get("url"),
    }
    desc = (fm.get("description") or "")
    out["description"] = desc[:2500]        # opisy z portali bywają ogromne i powtarzalne
    raw = fm.get("raw") or {}
    for k in ("parcel_no", "region_name", "distribution", "price_kind", "house_area_m2"):
        if raw.get(k):
            out[k] = raw[k]
    return {k: v for k, v in out.items() if v not in (None, "", [], {})}


def _extract_json(text: str) -> list:
    """Modele lokalne lubią dokleić komentarz albo ogrodzenie ```json — wyłuskujemy tablicę."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("w odpowiedzi nie ma tablicy JSON")
    return json.loads(text[start:end + 1])


def evaluate_batch(batch: list[dict], criteria: str, url: str, model: str,
                   timeout: float) -> list[dict]:
    payload = {
        "model": model,
        "temperature": 0.2,          # ocena ma być powtarzalna, nie twórcza
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content":
                "KRYTERIA KUPUJĄCEGO:\n" + criteria +
                "\n\nOFERTY DO OCENY (JSON):\n" + json.dumps(batch, ensure_ascii=False) +
                f"\n\nZwróć tablicę {len(batch)} obiektów — po jednym na każdą ofertę, w tej samej kolejności."},
        ],
    }
    r = httpx.post(f"{url.rstrip('/')}/chat/completions", json=payload,
                   headers={"Authorization": f"Bearer {API_KEY}"}, timeout=timeout)
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"]
    return _extract_json(content)


def normalize(item: dict, rec: dict) -> dict:
    fm = rec.get("frontmatter", rec)
    verdict = str(item.get("verdict", "")).strip().lower()
    if verdict not in VERDICTS:
        # lepiej wymusić weryfikację niż przyjąć nieznany werdykt jako dobry
        verdict = "do-weryfikacji"
    try:
        score = max(0, min(100, int(item.get("score", 0))))
    except (TypeError, ValueError):
        score = 0
    flags = item.get("flags") or []
    if not isinstance(flags, list):
        flags = [str(flags)]
    return {
        "id": fm.get("id"),
        "source": fm.get("source"),
        "source_id": fm.get("source_id"),
        "score": score,
        "verdict": verdict,
        "reason": str(item.get("reason", ""))[:600],
        "flags": [str(f)[:60] for f in flags][:8],
    }


def compare(ours: list[dict], other_path: str) -> dict:
    """Zestawienie z oceną referencyjną (np. z Claude) — po to, żeby decyzja o przejściu
    na lokalny model opierała się na liczbach, a nie na wrażeniu."""
    with open(other_path, encoding="utf-8") as fh:
        raw = json.load(fh)
    ref = raw if isinstance(raw, dict) else {r["id"]: r for r in raw}
    same = diff = 0
    moved: list[str] = []
    score_delta: list[int] = []
    for r in ours:
        o = ref.get(r["id"])
        if not o:
            continue
        if o.get("verdict") == r["verdict"]:
            same += 1
        else:
            diff += 1
            moved.append(f'{r["id"]}: {o.get("verdict")} → {r["verdict"]}')
        if isinstance(o.get("score"), int):
            score_delta.append(r["score"] - o["score"])
    return {
        "porownano": same + diff,
        "werdykt_zgodny": same,
        "werdykt_rozny": diff,
        "zgodnosc_proc": round(100 * same / max(1, same + diff)),
        "sredni_blad_score": round(sum(score_delta) / len(score_delta), 1) if score_delta else None,
        "rozbieznosci": moved[:25],
    }


def main(argv: list[str] | None = None) -> int:
    common.setup_utf8()
    p = argparse.ArgumentParser(description="Ocena ofert lokalnym modelem (API zgodne z OpenAI).")
    p.add_argument("--records-file", required=True, help="JSON: lista rekordów ofert")
    p.add_argument("--criteria", default=os.path.join(common.PROJECT_DIR, "properties", "criteria.md"))
    p.add_argument("--url", default=DEFAULT_URL, help="bazowy adres API, np. http://host:8080/v1")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--batch-size", type=int, default=8, dest="batch_size",
                   help="ile ofert na jedno zapytanie — małe modele gubią się przy dużych partiach")
    p.add_argument("--timeout", type=float, default=300.0)
    p.add_argument("--compare-with", dest="compare_with", default=None,
                   help="JSON z oceną referencyjną (np. z Claude) — policzy zgodność werdyktów")
    args = p.parse_args(argv)

    with open(args.records_file, encoding="utf-8") as fh:
        data = json.load(fh)
    records = data if isinstance(data, list) else list(data.values())
    criteria = _criteria_text(args.criteria)

    results: list[dict] = []
    errors: list[str] = []
    for i in range(0, len(records), args.batch_size):
        chunk = records[i:i + args.batch_size]
        slim = [_slim(r) for r in chunk]
        try:
            raw = evaluate_batch(slim, criteria, args.url, args.model, args.timeout)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"partia {i // args.batch_size + 1}: {exc}")
            # Partia przepadła, ale reszta ma się policzyć — brak oceny oznaczamy jawnie,
            # zamiast cicho pomijać ofertę (wtedy zniknęłaby z rankingu bez śladu).
            for rec in chunk:
                fm = rec.get("frontmatter", rec)
                results.append({"id": fm.get("id"), "source": fm.get("source"),
                                "source_id": fm.get("source_id"), "score": 0,
                                "verdict": "do-weryfikacji",
                                "reason": "ocena lokalnym modelem nie powiodła się",
                                "flags": ["blad-oceny"]})
            continue
        for rec, item in zip(chunk, raw):
            results.append(normalize(item if isinstance(item, dict) else {}, rec))
        sys.stderr.write(f"[eval_local] ocenione {min(i + args.batch_size, len(records))}/{len(records)}\n")

    meta = {"model": args.model, "url": args.url, "ocenionych": len(results),
            "batch_size": args.batch_size}
    if errors:
        meta["bledy"] = errors
    if args.compare_with:
        meta["porownanie"] = compare(results, args.compare_with)

    common.emit(results, meta)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
