---
name: properties-list-manage
description: "Zarządzanie listą działek: dodawanie/aktualizacja ogłoszeń (z URL, z rekordu wyszukiwania lub ręcznie z geoportalu), notatki, status nieaktualne, kontakt/MPZP/media, zbieranie zdjęć. Jedno źródło prawdy: properties/listings/*.md."
when_to_use: "dodaj działkę, dodaj ogłoszenie, wklej link do działki, zapisz działkę, zaktualizuj działkę, dopisz notatkę do działki, oznacz działkę jako nieaktualną, dodaj działkę z geoportalu, dodaj zdjęcia działki, lista działek, pokaż działki"
argument-hint: "<intencja, np. 'dodaj' i URL | 'notatka' | 'nieaktualne' | 'geoportal'> [--id YYYYMMDD_NNN]"
allowed-tools: Bash Read Glob
model: sonnet
---

# properties-list-manage — zarządzanie listą działek

Cienki orkiestrator nad przetestowanymi skryptami w `scripts/`. **Nie edytuj plików `.md` ręcznie** —
zawsze przez `manage_listing.py` (gwarantuje integralność frontmattera YAML i sekcji notatek/historii).

Jedyne źródło prawdy: `properties/listings/{YYYYMMDD_NNN}.md` (czyta je też strona Astro).
Wszystkie komendy uruchamiaj z katalogu projektu z prefiksem `PYTHONIOENCODING=utf-8`.

## Rozpoznanie intencji

Z wywołania ustal, co zrobić:

| Intencja | Sygnał w wywołaniu |
|----------|--------------------|
| Dodaj z linku | wklejony URL otodom/olx/gethome |
| Dodaj z wyszukiwania | rekord(y) JSON (zwykle wołane przez `properties-search`) |
| Dodaj z geoportalu | „geoportal", działka bez ogłoszenia (współrzędne/nr działki) |
| Notatka | „notatka", „zapisz że…" + `--id` |
| Nieaktualne | „nieaktualne", „sprzedane", „zdjęte" + `--id` |
| Kontakt/MPZP/media | „telefon", „MPZP", „media", „prąd/woda…" + `--id` |
| Zdjęcia | „dodaj zdjęcia", „pobierz zdjęcia" + `--id` |
| Pokaż listę | „lista", „pokaż działki" |

Jeśli brakuje `--id`, a jest potrzebny — pokaż listę (`manage_listing.py list`) i poproś o wskazanie.

## Procedury

### 1. Dodaj z wklejonego linku (tryb hybrydowy)
```
PYTHONIOENCODING=utf-8 python scripts/fetch_listing.py --url "<URL>" \
  | python -c "import sys,json;print(json.dumps(json.load(sys.stdin)['listings'][0],ensure_ascii=False))" \
  | PYTHONIOENCODING=utf-8 python scripts/manage_listing.py upsert --stdin
```
Następnie pobierz zdjęcia (patrz pkt 6) używając zwróconego `id`.
Jeśli `fetch_listing.py` zwróci `error` (zmiana struktury/blokada) — poinformuj i zaproponuj dodanie ręczne.

### 2. Dodaj/aktualizuj z rekordu wyszukiwania
Rekord JSON (jeden obiekt ze schematu scraperów) zapisz do pliku tymczasowego i:
```
PYTHONIOENCODING=utf-8 python scripts/manage_listing.py upsert --json-file <plik.json> --score <0-100>
```
Ponowny upsert tej samej oferty (ten sam source+source_id) **aktualizuje** istniejący plik (dedup) —
odświeża cenę/powierzchnię/zdjęcia, zachowuje notatki, kontakt, MPZP, status.

### 3. Dodaj pozycję z geoportalu (bez ogłoszenia)
Zbuduj rekord ręcznie (wymagane: tytuł, powierzchnia, współrzędne lat/lon; opcjonalnie cena/MPZP),
ustaw `source: "geoportal"` i unikalny `source_id` (np. obręb + nr działki):
```
echo '{"source":"geoportal","source_id":"Boguszow_125-7","url":null,
"title":"Boguszów dz. 125/7 (geoportal)","area_m2":1500,"transaction":"sale",
"location":{"city":"Boguszów-Gorce","region":"dolnośląskie","address":"obręb Boguszów, dz. 125/7"},
"lat":51.0123,"lon":17.1456,"coords_approx":false}' \
| PYTHONIOENCODING=utf-8 python scripts/manage_listing.py upsert --stdin --source-type geoportal
```

### 4. Notatka
```
PYTHONIOENCODING=utf-8 python scripts/manage_listing.py note --id <ID> --text "<treść>"
```

### 5. Status / kontakt / MPZP / media
```
PYTHONIOENCODING=utf-8 python scripts/manage_listing.py set-status --id <ID> --status inactive
PYTHONIOENCODING=utf-8 python scripts/manage_listing.py set --id <ID> --field contact.phone --value "600100200"
PYTHONIOENCODING=utf-8 python scripts/manage_listing.py set --id <ID> --field mpzp.status --value "MN — zabudowa jednorodzinna"
PYTHONIOENCODING=utf-8 python scripts/manage_listing.py set --id <ID> --field media.prad --value true
PYTHONIOENCODING=utf-8 python scripts/manage_listing.py set --id <ID> --field land_type --value "budowlana"
```
**Rodzaj działki** (`land_type`): `rolna` | `siedliskowa` | `budowlana` (pokazywany na karcie pod powierzchnią).
Pola złożone (kropką): `contact.{name,phone,email}`, `mpzp.{status,link,note}`, `media.{prad,woda,kanalizacja,gaz}`.
Wartość jest parsowana jako JSON (`true`/`123`/`"tekst"`), więc liczby i bool zapisują się poprawnie.

### 6. Zdjęcia
Z URL-i z ogłoszenia (pole `images`):
```
PYTHONIOENCODING=utf-8 python scripts/fetch_photos.py --id <ID> --max 12
```
Z lokalnych plików (np. zdjęcia z wizji lokalnej):
```
PYTHONIOENCODING=utf-8 python scripts/manage_listing.py add-photo --id <ID> --file "C:/ścieżka/foto1.jpg" --file "C:/ścieżka/foto2.jpg"
```

### 7. Lista / podgląd
```
PYTHONIOENCODING=utf-8 python scripts/manage_listing.py list            # tabela
PYTHONIOENCODING=utf-8 python scripts/manage_listing.py list --status active --json
PYTHONIOENCODING=utf-8 python scripts/manage_listing.py get --id <ID>   # pełny JSON jednej pozycji
```

## Output

Po wykonaniu zwróć zwięźle:
- jaką operację wykonano i na którym `id`,
- kluczowe dane pozycji (tytuł, cena, powierzchnia, miejscowość, status),
- ile zdjęć pobrano (jeśli dotyczy),
- przypomnienie: zmiany są od razu widoczne na stronie (to samo źródło `.md`).

Przy `list`/`get`/`pokaż działki` oraz wszędzie, gdzie prezentujesz oferty z ogłoszeń, **podawaj klikalny
link do ogłoszenia** `[link](URL)` z pola `url`. Pozycje `source_type: geoportal` (bez ogłoszenia) → „—".

## Zasady

- **Nigdy nie edytuj plików `.md` ręcznie** — tylko przez `manage_listing.py`.
- **Dedup po (source, source_id)** — nie twórz duplikatów; ponowne dodanie = aktualizacja.
- **Nie nadpisuj danych użytkownika** (notatki, kontakt, MPZP, media, status) przy aktualizacji ze źródła.
- **Brak `--id`** dla operacji wymagającej pozycji → najpierw `list`, potem dopytaj.
- **Zgłaszaj błędy wprost** — jeśli skrypt zwróci `error`, pokaż go i zaproponuj alternatywę (np. dodanie ręczne).
- Działki z geoportalu mają `source_type: geoportal` i `source: geoportal` — nie mylić z ogłoszeniami.
