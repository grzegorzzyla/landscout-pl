# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Czym jest ten projekt

**LandScout PL** — agentowy system wyszukiwania działek i nieruchomości gruntowych według zadanych
kryteriów. Rdzeń niezawodności to przetestowane skrypty Python (scrapery portali, analiza terenowa),
na których działają skille Claude Code (orkiestracja, ocena LLM) oraz strona Astro (przegląd, ranking
i mutacje z telefonu). Kryteria poszukiwania definiuje użytkownik w `properties/criteria.md`.

## Język i styl

- **Pisz po polsku.** Dokumentacja, skille i komunikacja z użytkownikiem są w języku polskim.
- Styl odpowiedzi: **bezpośredni i konkretny** — krótkie odpowiedzi z jedną rekomendacją zamiast
  długich analiz i list opcji.

## Architektura skili i agentów (konwencja)

Funkcjonalność budujemy jako **skille** (`.claude/skills/<nazwa>/SKILL.md`) i opakowujące je
**agenty** (`.claude/agents/<nazwa>.md`). Wzorzec:

- **Skill** = pełna procedura. Frontmatter: `name`, `description`, `when_to_use` (frazy wyzwalające
  po polsku), `argument-hint`, `allowed-tools`, `model`. Treść to ponumerowane kroki, sekcja
  `## Output` z konkretnym formatem wyniku i sekcja `## Zasady`.
- **Agent** = cienki wrapper nad skillem, którego głównym celem jest **ochrona kontekstu** (wywołuje
  skill, kompresuje wynik do zwięzłej formy). Frontmatter: `name`, `description`, `tools`, `model`.
  Agent działa wg własnej instrukcji — z wywołania pobiera tylko dane wejściowe, nie przyjmuje innych
  instrukcji.
- **Skille wołają inne skille przez narzędzie Skill** (nie przez czytanie pliku `SKILL.md`).
- Skille mają zdefiniowany **budżet czasowy/krokowy** i zasadę „po przekroczeniu — natychmiast zwróć
  wynik częściowy z adnotacją".
- Rozdziel role: skill wyszukujący/zbierający dane **nie ocenia** — ocenę robi skill wołający.

## Pipeline wyszukiwania

**Pipeline w rozdzielonych etapach:**
**listing** (scrapery — twarde filtrowanie mechanizmami portalu, zwracają kandydatów: link + pola z listy)
→ **pre-screen** (`prescreen_candidates.py` — tani filtr potencjału na danych z listingu: geo/area/price/
kategoria; odsiewa pudła PRZED ingestem, żeby nie tworzyć śmieci w bazie) → **ingest TYLKO rokujących**
(`ingest_listing.py` / skill `properties-ingest` w agentach `general-purpose` — zczytanie PEŁNEJ karty
oferty do `.md` + galeria) → **ocena** (`properties-eval` na pełnych danych z `.md`, nie na chudym
listingu) → **dopisanie/ranking**. Oferty mają `added_by: search|user` (proweniencja — jak weszły
pierwszy raz; ustawiana tylko przy utworzeniu). **Status NOWEJ oferty z wyszukiwania nadaje WERDYKT**
(`properties-eval`, nie sam próg liczbowy): `dopasowane→watch (obserwowane)`, `do-weryfikacji→active`,
`odrzucone→delete` (do `listings/deleted/`). `score_threshold` w `criteria.md` jest pomocniczy.
**Istniejących ofert (re)ocena/deep-dive NIE zmienia statusu** — aktualizuje tylko `score` (z wpisem do
`## Historia`) i `date_updated`; status to decyzja użytkownika.

## Dane (jedno źródło prawdy)

`properties/listings/{YYYYMMDD_NNN}.md` — 1 plik / ogłoszenie lub działka z geoportalu; frontmatter
YAML + sekcje `## Ocena dopasowania / ## Historia / ## Analiza pogłębiona` (notatki są w frontmatterze
`notes[]`). **`properties/listings/deleted/`** — oferty skasowane (poza listą, stroną i licznikiem;
używane tylko do dedup w wyszukiwaniu; przywracane ręcznie). Kryteria w `properties/criteria.md`
(frontmatter z parametrami + proza „opis poszukiwanej działki" do oceny). Zdjęcia w
`properties/photos/{id}/`. Rejestr grup Facebooka w `properties/facebook_groups.json` (utwórz z
`facebook_groups.example.json`). Katalogi `listings/` i `photos/` oraz `facebook_groups.json` są
w `.gitignore` — baza ofert to prywatne dane użytkownika (PII z ogłoszeń) i nie trafia do repo.
**Nigdy nie edytuj plików `.md` ręcznie — tylko przez `scripts/manage_listing.py`.**

## Skrypty (`scripts/`, uruchamiaj z prefiksem `PYTHONIOENCODING=utf-8`)

- `scrape_olx.py` (OLX JSON API), `scrape_otodom.py` (Otodom `__NEXT_DATA__` + fallback Playwright),
  `scrape_morizon.py` (Morizon — JSON-LD `AggregateOffer.offers[]`; 1. strona wyników/miejscowość, filtry
  area/price/geo realizuje pre-screen; galeria z dekodowania base64 miniatur), `scrape_gethome.py` (backup)
  — listowanie, wspólny schemat w `common.py`. Lista portali w `properties-search` przez `--portals`
  (domyślnie `olx,otodom,morizon`). Przełącznik `--kind dzialka|dom`
  (domyślnie `dzialka`); `dom` obejmuje domy/siedliska/gospodarstwa. Dla `kind=dom` rekord `area_m2` to
  powierzchnia **działki/terenu** (pow. budynku w `raw.house_area_m2`); kategorie/filtry zweryfikowane
  empirycznie (OLX cat 18 + `filter_float_area`, Otodom segment `dom` + `terrainAreaMin/Max`, gethome `/domy/`).
- `scrape_kowr.py` — **zasób KOWR** (nieruchomoscikowr.gov.pl): państwowa ziemia rolna z **przetargów**,
  niedostępna na żadnym portalu ogłoszeniowym. Ważne różnice od portali: cena to **wywoławcza**
  (`raw.price_kind`), część oferty to **dzierżawa** (`raw.distribution`; domyślnie zwracamy sprzedaż),
  a tytuł zawiera powiat/gminę/obręb i **numer działki** → `raw.parcel_no` + `raw.region_name`, którymi
  `geo_analyze.py --parcel-no --region-name` potwierdza działkę (przy portalach numeru zwykle brak).
  Portal **nie ma współrzędnych ani działającego filtra lokalizacji w URL** (pole `location` to
  autouzupełnianie, ignorowane) — powierzchnię/cenę filtruje serwer, lokalizację dopasowujemy po nazwach
  z tytułu (miejscowość + jej powiat), a dokładny dystans liczy pre-screen. Stąd **dzienny cache**
  (`scripts/.cache/kowr_RRRRMMDD_*.json`): pełne przejście to kilka stron, a wyszukiwanie pyta raz na
  lokalizację; `--refresh` wymusza pobranie. Tytuły mają 5 różnych formatów — parser obsługuje wszystkie.
- `scrape_adresowo.py` — **adresowo.pl**: portal ogłoszeń **bezpośrednio od właścicieli** (pośrednicy
  tylko płatnie), więc inna podaż niż OLX/Otodom/Morizon. Obsługuje **wiele gmin naraz**, czego portale
  nie dają: adres ma postać `/f/dzialki/<id_gminy>_<id_gminy>_…/<kod_filtrów>` (`z3`–`z8` = typy działki,
  `zb` = źródło bezpośrednie), paginacja to sufiks `_l2`, `_l3`. Identyfikatory gmin są wewnętrzne dla
  portalu i nie da się ich wyliczyć z nazwy — dlatego lokalizacje mapuje
  `properties/adresowo_searches.json` (nazwa z `criteria.md` → gotowy adres zapisanego wyszukiwania,
  skopiowany z paska przeglądarki); bez wpisu scraper próbuje strony miasta `/dzialki/<slug>/`.
  **Dwie pułapki parsowania, obie ciche:** powierzchnia bywa podana w **ha**, nie w m² (regex liczący
  tylko `m²` gubi WSZYSTKIE duże działki — czyli dokładnie te szukane), a separator tysięcy w cenie
  przychodzi jako encja `&nbsp;`, nie jako `\u00a0` (wtedy wszystkie ceny wychodzą puste, a powierzchnie
  przechodzą i parser wygląda na sprawny). Encje normalizowane przy pobraniu strony.
- `scrape_facebook.py` — deterministyczny czytnik nowych postów z zarejestrowanych grup FB (Playwright,
  trwały profil w `scripts/.fb_profile/` — gitignored); tryby `--login`, `--add-group`, `--scan`, `--commit`.
  Rejestr grup i znaczniki „ostatnio przeczytane" w `fb_groups.py`.
- `fetch_listing.py --url` — pojedyncze ogłoszenie z wklejonego linku (OLX/Otodom/Morizon/gethome); typ
  (`dzialka`/`dom`) rozpoznawany automatycznie z danych strony. Zwraca surowy rekord (nie zapisuje).
- `prescreen_candidates.py --candidates-file [--max-dist-km 50]` — etap **pre-screen**: tani filtr na
  danych z listingu (geo: dystans od lokalizacji docelowych z `criteria.md`; area<min; price>max; kategoria
  ROD/przemysł/udział). Zwraca `kept`/`rejected` + `meta.dropped`; tylko `kept` idzie do ingestu. Brak
  współrzędnych → nie odrzuca. Cel: nie zczytywać pełnych kart pudeł.
- `ingest_listing.py --url|--urls-file [--added-by search|user]` — etap **ingest**: zczytuje PEŁNĄ kartę
  (przez `fetch_listing`) i **zapisuje do `.md`** + pobiera pełną galerię; idempotentny (ponowny ingest
  odświeża, nie dubluje zdjęć, zachowuje proweniencję i pola użytkownika). Jeden punkt wejścia dla skilla
  `properties-ingest` (agenci) oraz dla endpointu strony (ręczne dodanie linku).
- `manage_listing.py` (upsert/note/set-status/set/set-tags/set-section/seen/delete/known-sources/add-photo/list/get) —
  bezpieczny merge frontmattera, ID `YYYYMMDD_NNN`, dedup po (source, source_id). Statusy:
  `active/inactive/watch/favorite` (`favorite` = Ulubione → cel pogłębionej analizy). `delete` przenosi
  ofertę do **`properties/listings/deleted/`** (SKASOWANA — poza listą i stroną, usuwa zdjęcia; przywrócenie
  tylko ręczne przez przeniesienie pliku z powrotem). `known-sources` zwraca (source, source_id) z `listings/`
  **i** `deleted/` — do dedup w wyszukiwaniu (oferta raz skasowana nie wraca przez ingest). `set-section`
  zapisuje/zastępuje sekcję treści. `set-tags --tags "a,b,c"` zastępuje całą listę tagów oferty
  (frontmatter `tags[]`; trim + dedup case-insensitive; pusto = wyczyść). `fetch_photos.py --id` — pobranie zdjęć.
- `geo_analyze.py --id|--lat/--lon [--parcel-no N …] [--region-name NAZWA …]` — pogłębiona analiza terenowa
  (rdzeń skilla `properties-deep-dive`): ULDK GUGiK (nr działki + województwo/powiat/gmina/obręb + geometria),
  NMT GUGiK (wysokość n.p.m., nachylenie, ekspozycja stoku — własna konwersja WGS84→PL-1992, bez `pyproj`),
  Overpass/OSM (najbliższe kolej/sklep/szpital/woda + dystanse) oraz deep-linki do ręcznej weryfikacji
  MPZP/RCiWN/KW. **Numer działki ma pierwszeństwo nad współrzędnymi z portalu** (te bywają adresem agencji):
  z `--parcel-no` skrypt rozwiązuje działkę najpierw **po nazwie obrębu** (`--region-name` → ULDK
  `GetParcelByIdOrNr`), walidując wynik powiatem spod współrzędnych + powierzchnią z oferty, a dopiero potem
  fallbackiem po obrębie spod współrzędnych (`GetParcelById`); przy sukcesie zwraca realną geometrię
  (`confirmed=true`, `coords_orientacyjne=false`, pozycja z geoportalu). **Uwaga:** bez rozwiązanego numeru,
  przy `coords_approx: true` (Otodom, część OLX) współrzędne to centroid miejscowości — `parcel`/`terrain`
  są poglądowe (sygnał: `area_m2_geom` ≠ `area_m2` z oferty). MPZP/transakcje/właściciel nie mają
  otwartego API — skrypt zwraca wskazówki, nie dane.
  Sekcja **`nuisances`** (`--nuisance-radius`, domyślnie 2500 m) — to, o czym ogłoszenie milczy: czynna
  linia kolejowa, droga krajowa/ekspresowa (także w budowie), cmentarz, zabudowa zagrodowa/ferma, przemysł,
  wyrobisko, składowisko, oczyszczalnia, wiatraki, linie NN. Odległość do obiektów liniowych liczona do
  **geometrii**, nie do centroidu (centroid 20-km linii kolejowej leży kilkanaście km od działki, obok
  której ta linia przechodzi). Przekroczenie progu → ostrzeżenie w `notes`. Osobne, małe zapytanie —
  `pois` (udogodnienia, 15 km) i `nuisances` (uciążliwości, 2,5 km) to dwa różne zapytania, bo łączne
  wpadało w timeout Overpassa.
  **NMT — kolejność osi:** `wgs84_to_pl1992()` zwraca `(easting, northing)`, a GUGiK `GetHByXY` oczekuje
  `x = northing, y = easting`. Pomylenie ich daje wysokość innego miejsca albo `0` (punkt poza zasięgiem) —
  dlatego `_nmt_height(northing, easting)` ma taką sygnaturę, a dokładne `0.0` jest traktowane jako BRAK
  odczytu, nie jako poziom morza. Test kontrolny: Śnieżka ma wychodzić 1602,9 m.
- `eval_local.py --records-file [--url --model --batch-size --compare-with]` — ocena ofert
  **lokalnym modelem** przez API zgodne z OpenAI (llama.cpp/Ollama/vLLM). Ten sam kontrakt co skill
  `properties-eval`, więc oba są wymienne. Sens: scoring to najdroższy etap pipeline'u (miliony
  tokenów przy kilkuset ofertach), a jest w zasięgu modelu 27–30B — orkiestracji i oględzin zdjęć
  NIE przenosimy. Rekord jest odchudzany przed wysłaniem (bez zdjęć i surowych danych portalu),
  bo okno małego modelu jest cenne. `--compare-with` zestawia werdykty z oceną referencyjną —
  decyzja o przejściu na lokalny model ma się opierać na liczbach, nie na wrażeniu.
  Włącznik w panelu agentury (`/agentura`), adres w `LOCAL_LLM_URL`.
- `geoportal_link.py` — link do krajowego geoportalu z identyfikatora działki (TERYT) lub z oferty.

## Skille

`properties-search` (orkiestruje pipeline: listing → ingest → ocena → ranking/dopisanie;
tryb `autonomiczny`/`interaktywny`), `properties-ingest` (zczytanie pełnych kart do `.md` z listy linków,
w agentach `general-purpose`), `properties-eval` (ocena/scoring na pełnych danych z `.md`),
`properties-list-manage` (CRUD listy, zdjęcia, pozycje geoportal), `properties-photos`
(wzrokowy wybór zdjęcia głównego `cover` + wykrycie `map_photo` mapki/planu; w agentach `general-purpose`),
`properties-deep-dive`
(pogłębiona analiza: `geo_analyze.py` + oględziny zdjęć → sekcja `## Analiza pogłębiona`; **nie zmienia
statusu** oferty; uruchamiać przez agenta `general-purpose` — czytanie zdjęć jest kontekstowo ciężkie).
Strona ma endpoint `POST /api/reeval` (zmiana notatki → ponowna ocena: score + sekcja + wpis do historii,
bez zmiany statusu). **Każda prezentacja oferty z ogłoszenia musi zawierać link do ogłoszenia.**

## Strona (`site/`, Astro 5, tryb SSR + `@astrojs/node`)

Strony (`index`, `/dzialka/[id]`) mają `prerender = false` i czytają `../properties/listings/*.md`
**wprost z dysku na każde żądanie** (`src/server/listings.ts` — `gray-matter` na frontmatter + `marked`
na treść), bez content-layer cache — każda mutacja (status/notatki/deep-dive) widoczna natychmiast po
odświeżeniu. Interaktywność przez endpointy `src/pages/api/*`. Zdjęcia: dowiązanie
`site/public/photos → properties/photos` — na Windows **junction**, na macOS/Linux **symlink**:
`mkdir -p site/public && ln -s ../../properties/photos site/public/photos`. **Bez niego galeria jest pusta**
(pliki leżą na dysku, ale strona nie ma ich czym podać) — to pierwsza rzecz do sprawdzenia po klonie repo. Statusy w UI:
**active / watch (obserwowane) / favorite (ulubione) / inactive**; filtr „obserwowane" pokazuje też
ulubione (oba = „do obejrzenia"). Pole **`land_type`** (rodzaj: rolna/siedliskowa/budowlana) na karcie
pod powierzchnią. Galeria-lightbox (na mobile poziomy pasek), mapa pełnoekranowa (klasa `.fs`, działa na
mobile), `cover`/`map_photo`, sortowanie (ocena/data dodania/aktualizacji), zachowanie filtrów i pozycji
listy. Dostęp: prosta bramka na wspólne hasło + podpisana sesja (`src/server/auth.ts`; konfiguracja w
`site/.env` — utwórz z `.env.example`). Uruchomienie dla telefonu (np. Tailscale): `cd site && npm run
start` (host 0.0.0.0:4321; dodatkowe hosty dev-serwera w env `ALLOWED_HOSTS`). Build: `npm run build`.

## Backend strony (`site/src/server/runner.ts` + `src/pages/api/`)

Mutacje i wyzwalanie skili. `POST /api/status` (deterministyczne, `manage_listing set-status`);
`POST /api/add` (ręczne dodanie z linku — odpala **Claude Code headless ze skillem `properties-ingest`**,
by agent radził sobie z błędami portalu); `POST /api/deepdive` (odpala skill `properties-deep-dive`;
można ponawiać); `POST /api/note` (notatki add/edit/delete — `manage_listing note-add|note-edit|note-delete`,
frontmatter `notes[{id,ts,text}]`; UI aktualizuje DOM w miejscu, bez reloadu); `POST /api/tags`
(deterministyczne, `manage_listing set-tags`; zastępuje całą listę tagów oferty — na karcie oferty popup
zaznacza istniejące / dopisuje nowe, na liście filtr „Tagi" pokazuje oferty ze WSZYSTKIMI zaznaczonymi
tagami); `GET /api/job/<id>` (status zadania — UI poll-uje i odświeża). Reload po mutacji jest
natychmiastowy (strony czytają `.md` świeżo z dysku — patrz wyżej). Claude Code uruchamiany przez launcher
**`bin/cdp`** (w repo — patrz `bin/README.md`): `runner.ts` bierze ścieżkę binarki z `cdp --which`
(kolejność: `CLAUDE_EXE` → najnowszy `%APPDATA%\Claude\claude-code\<wer>\claude.exe` → `claude` z PATH),
a prompt podaje binarce wprost przez argv (`-p … --dangerously-skip-permissions`, stdin odcięty).
⭐ Ulubione wyzwala deep-dive, jeśli go wcześniej nie było (rozdzielone od ręcznego „Uruchom deep-dive").

## Zależności

`pip install -r scripts/requirements.txt` (httpx, lxml, PyYAML, playwright). Fallback Otodom oraz
skaner Facebooka wymagają `python -m playwright install chromium`.
**Sprawdź, którym interpreterem masz zależności** — na macOS `python` bywa innym Pythonem niż ten, do
którego `pip` instalował (`python -c "import yaml"`); wtedy uruchamiaj skrypty przez `python3`.

## Uwagi techniczne

- Zewnętrzne `<script src>` w Astro oznaczaj `is:inline` (inaczej Astro je usuwa).
- Konsola Windows to cp1250 — skrypty wymuszają UTF-8 na stdout (`common.setup_utf8()`).
