---
name: properties-ingest
description: "Zczytuje PEŁNE dane z karty ogłoszenia (jeden link lub lista linków) do plików properties/listings/*.md wraz z pełną galerią zdjęć. Etap 'ingest' między wyszukiwaniem (twarde filtrowanie na listingu) a oceną. Nie ocenia. Przeznaczony do uruchamiania w agencie general-purpose (równolegle, partiami linków)."
when_to_use: "zczytaj ofertę z linku, pobierz pełne dane oferty, ingest ogłoszeń, dodaj oferty z listy linków, wczytaj karty ogłoszeń do bazy, dodaj ogłoszenie ze strony"
argument-hint: "<URL albo lista URL-i> [--added-by search|user]"
allowed-tools: Bash
model: sonnet
---

# properties-ingest — zczytanie pełnych danych z karty oferty do .md

Bierzesz **link(i)** do kart ogłoszeń i zapisujesz z nich **komplet danych** do `properties/listings/*.md`.
To etap pośredni pipeline'u: **wyszukiwanie** (scrapery, twarde filtrowanie na listingu portalu) →
**ingest (ten skill)** → **ocena** (`properties-eval` na danych z `.md`). Karta oferty ma znacznie więcej
informacji niż listing — dlatego ocena MUSI działać na danych z ingestu, nie z chudego listingu.

> **Rozdział ról:** ten skill tylko *zczytuje i zapisuje* (nie ocenia, nie filtruje). Rdzeń to przetestowany
> `scripts/ingest_listing.py` (karta przez httpx/curl, Otodom z fallbackiem Playwright → `manage_listing
> upsert` → pełna galeria). Uruchamiaj z katalogu projektu, prefiks `PYTHONIOENCODING=utf-8`.

## Wejście
- **Jeden link** → `--url`.
- **Wiele linków** → zapisz po jednym w linii do pliku tymczasowego i użyj `--urls-file`.
- `--added-by`: `search` (domyślnie; gdy ingest jest skutkiem wyszukiwania) albo `user` (ręczne dodanie
  linku przez użytkownika ze strony).
- Opcjonalnie `--score N` przy dodaniu z wyszukiwania (jeśli ocena już policzona).

## Krok 1: Ingest
Jeden link:
```
PYTHONIOENCODING=utf-8 python scripts/ingest_listing.py --url "<URL>" --added-by <search|user>
```
Lista linków (partia — typowo cała robota jednego agenta general-purpose):
```
printf '%s\n' "<URL1>" "<URL2>" ... > /tmp/ingest_links.txt
PYTHONIOENCODING=utf-8 python scripts/ingest_listing.py --urls-file /tmp/ingest_links.txt --added-by search
```
Skrypt jest **idempotentny**: ponowny ingest tego samego linku aktualizuje rekord i odświeża galerię
(bez duplikatów), zachowując `added_by` z pierwszego wejścia oraz pola użytkownika (notatki, status, kontakt).

**Rodzaj działki (`land_type`):** ingest zgrubnie rozpoznaje rodzaj (`rolna`/`siedliskowa`/`budowlana`) z karty
i ustawia go, **gdy jeszcze nieoznaczony** (nie nadpisuje ręcznego/deep-dive). Jeśli z opisu jednoznacznie
wynika inny rodzaj niż heurystyka, popraw:
`PYTHONIOENCODING=utf-8 python scripts/manage_listing.py set --id <id> --field land_type --value <rolna|siedliskowa|budowlana>`.

## Krok 2: Zwróć wynik
Skrypt wypisuje JSON `{url, id, created, source, title, photos, error}` (obiekt lub tablica). Przekaż dalej
**zwięźle**: dla każdej pozycji `id`, `created` (nowy/aktualizacja), liczbę zdjęć, ewentualny `error`.
Pozycje z `error` (blokada/zmiana struktury karty) wymień osobno — nie udawaj, że się powiodły.

## Orkiestracja (jak woła to wyszukiwanie / strona)
- **`properties-search`**: po twardym filtrowaniu na listingu dzieli linki kandydatów na partie i uruchamia
  **równolegle agentów `general-purpose`**, każdemu zlecając ten skill na jednej partii linków
  (ochrona kontekstu — ciężkie pobieranie kart poza głównym wątkiem). Dopiero potem `properties-eval`.
- **Ręczne dodanie ze strony**: endpoint odpala Claude Code z tym skillem na jednym linku, `--added-by user`.

## Zasady
- **Nie oceniaj** (to robi `properties-eval`) i **nie filtruj** (to robi scraper na listingu).
- **Zgłaszaj błędy wprost** — `error` z wyniku skryptu idzie do raportu; nie pomijaj po cichu.
- **Budżet**: ~1 wywołanie skryptu na partię linków; przy dużej liście dziel na partie ~10–15 linków na agenta.
- **Zapis tylko przez skrypty** (`ingest_listing.py`/`manage_listing.py`) — nigdy ręcznie w plikach `.md`.
