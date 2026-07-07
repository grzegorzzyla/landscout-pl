---
name: properties-search
description: "Wyszukiwanie działek wg zapamiętanych kryteriów (properties/criteria.md): przeszukuje portale (OLX/Otodom/Morizon/gethome) oraz zarejestrowane grupy Facebook przetestowanymi skryptami, ocenia dopasowanie każdego ogłoszenia do opisu i (tryb autonomiczny) dopisuje trafione do listy lub (tryb interaktywny) prezentuje ranking do akceptacji."
when_to_use: "szukaj działek, znajdź działki, przeszukaj oferty działek, nowe działki, sprawdź oferty, wyszukaj grunty, monitoruj działki, co nowego w działkach, skanuj grupy FB, dodaj grupę FB, co nowego na facebooku"
argument-hint: "[dowolne uwagi tekstem] [--tryb autonomiczny|interaktywny] [--portals olx,otodom,morizon,gethome] [--location MIEJSCOWOSC] [--max N]"
allowed-tools: Bash Read Glob Skill Task
model: sonnet
---

# properties-search — wyszukiwanie i ocena działek

Realizuje pełny cykl w **rozdzielonych etapach**:
**listing = twarde filtrowanie** (mechanizmy portalu) → **pre-screen** (tani filtr potencjału na danych
z listingu: geo/area/price/kategoria — `prescreen_candidates.py`) → **ingest = zczytanie pełnych kart do
`.md` TYLKO dla rokujących** (skill `properties-ingest` w agentach `general-purpose`) → **ocena na pełnych
danych** (`properties-eval`) → **dopisanie/ranking**. 
Dwie zasady kluczowe: 
(1) pełną kartę zczytujemy **dopiero po** przejściu pre-screenu — żeby nie tworzyć w bazie śmieci (pudeł geograficznych itp.);
(2) ocena jakościowa MUSI działać na **pełnych danych z karty** (z `.md` po ingeście), bo karta ma znacznie
więcej informacji niż listing. Rdzeń niezawodności to przetestowane skrypty w `scripts/`.
Komendy uruchamiaj z katalogu projektu, prefiks `PYTHONIOENCODING=utf-8`.

## Tryby
- **interaktywny** (domyślny) — prezentuje ranking kandydatów z linkami i oceną; dopisuje TYLKO te
  wskazane przez użytkownika (lub linki, które wklei).
- **autonomiczny** — sam dopisuje wszystkie pozycje z oceną ≥ `score_threshold` z kryteriów.

## Krok wejściowy: zinterpretuj polecenie i uwagi (DYSPOZYTOR — wykonaj ZAWSZE jako pierwszy)
Wywołanie to **dowolny tekst** (z czatu lub ze strony „Szukaj w sieci") — może zawierać flagi (`--…`) i/lub
**uwagi po polsku**. Najpierw rozłóż polecenie na decyzje, a dopiero potem wykonuj kolejne kroki. Zacznij
od jednozdaniowego echa: „Rozumiem polecenie jako: <tryb pracy> + <nadpisania> + <akcenty>" — żeby było
jasne, co zaraz zrobisz.

**A. Wybierz TRYB PRACY** (decyduje, które kroki uruchamiasz):
| Sygnał w poleceniu | Tryb pracy | Wykonaj kroki |
|---|---|---|
| brak linków, „szukaj/znajdź/przeszukaj/co nowego/monitoruj" | **PEŁNE WYSZUKIWANIE** (domyślny) | 0 → 1 → **1b (grupy FB)** → 2 → 3 → 4 → 5 → 5b → 6 |
| wklejone URL-e ogłoszeń („dodaj te linki", „weź to") | **DODAJ Z LINKÓW** | 0 → 3 (`--added-by user`, **te konkretne URL-e**, bez listingu/pre-screenu) → 4 → 5 → 5b |
| wklejony link grupy FB lub „dodaj grupę FB: <link>" (`facebook.com/.../groups` lub `facebook.com/share/g/…`) | **REJESTRACJA GRUPY FB** | tylko `scrape_facebook.py --add-group <URL>`; potwierdź id/nazwę; bez wyszukiwania |
| „skanuj grupy FB / sprawdź grupy / co nowego na FB" | **TYLKO GRUPY FB** | 0 → 1b → 2 → 3 → 4 → 5 → 5b → 6 (pomiń Krok 1/portale) |
| „przeoceń / oceń ponownie / zważ pod kątem… / zaktualizuj oceny" bez nowych źródeł | **PRZEOCEŃ ISTNIEJĄCE** | 0 → 4 na ofertach już w `listings/` → 5 **tylko zapis score+`## Historia`+sekcja, STATUSU NIE RUSZAJ** |

W razie wątpliwości (np. są i linki, i prośba o szukanie) — wykonaj oba: najpierw DODAJ Z LINKÓW, potem PEŁNE WYSZUKIWANIE.

**B. Wyłuskaj NADPISANIA parametrów** z uwag (override na `criteria.md`; flaga `--…` ma pierwszeństwo nad prozą):
| Uwaga w prompcie | Nadpisanie |
|---|---|
| „w Walimiu i Głuszycy", „okolice Barda" | `locations[]` ← tylko wymienione (z `--location` jeśli podane) |
| „tylko otodom", „bez OLX", „dorzuć gethome" | lista portali (Krok 1) — odpowiednio zawęź/rozszerz; domyślnie `olx,otodom,morizon` |
| „tylko domy / siedliska", „tylko działki", „działki i domy" | `--kind`: `dom` / `dzialka` / oba (uruchom Krok 1 dwukrotnie) |
| „do 500 tys", „od 4000 m²", „większe niż…", „taniej" | `price_max` / `area_min` / `area_max` |
| „szerzej", „dalej", „w promieniu 60 km", „więcej wyników" | `distance_km` / `--max-dist-km` (Krok 2) / `--max` na źródło — w górę |
| „bez FB", „tylko portale" | pomiń Krok 1b (nie skanuj grup FB) |
| „tryb autonomiczny / sam dopisz" | TRYB = autonomiczny (inaczej interaktywny) |

**C. Wychwyć AKCENTY JAKOŚCIOWE** (cisza, las, widok na góry, blisko potoku/rzeki, południowy stok, dojazd
asfaltem, media w działce, z dala od drogi szybkiego ruchu itp.). **To NIE są twarde filtry** — przekaż je
**dosłownie do oceny** (Krok 4) jako dodatkowy nacisk dla `properties-eval` (sekcja „dodatkowe akcenty:
…"). Nie zawężają one listingu/pre-screenu — wpływają tylko na `score`/`reason`.

Wszystko, czego uwagi nie nadpisują, bierz z `criteria.md` (Krok 0). Jeśli polecenie jest puste/ogólne —
PEŁNE WYSZUKIWANIE na czystych kryteriach.

## Krok 0: Wczytaj kryteria
Przeczytaj `properties/criteria.md`. Z frontmattera weź: `transaction`, `locations[]` (każda z
`distance_km`), `area_min/max`, `price_min/max`, `score_threshold`, `include_homes` (bool). Z treści weź
**opis poszukiwanej działki** (do oceny). Argumenty wywołania nadpisują kryteria (np. `--location`, `--max`).

**Portale do przeszukania** bierz z argumentu `--portals` (lista po przecinku). Domyślnie: **`olx,otodom,morizon`**
(gethome dorzuć jako backup, gdy łącznie mało wyników). Skrypt na portal: `scrape_olx.py`, `scrape_otodom.py`,
`scrape_morizon.py`, `scrape_gethome.py` — wszystkie dają ten sam schemat rekordu i flagę `--kind dzialka|dom`.

## Krok 1: Listowanie (przetestowane skrypty)
Dla **każdej** lokalizacji z kryteriów uruchom skrypty **wybranych portali** (`--portals`). Przykład dla
jednej lokalizacji (podstaw wartości z kryteriów):
```
PYTHONIOENCODING=utf-8 python scripts/scrape_olx.py     --location "Kłodzko" --distance 15 --area-min 1000 --area-max 3500 --price-max 700000 --max 60 > /tmp/olx.json
PYTHONIOENCODING=utf-8 python scripts/scrape_otodom.py  --location "Kłodzko" --distance 15 --area-min 1000 --area-max 3500 --price-max 700000 --max 60 > /tmp/oto.json
PYTHONIOENCODING=utf-8 python scripts/scrape_morizon.py --location "Kłodzko" --area-min 1000 --area-max 3500 --price-max 700000 --max 60 > /tmp/mor.json
```
**Morizon**: filtry area/price/promień realizuje pre-screen (Krok 2), nie portal; scraper zwraca 1. stronę
wyników per miejscowość (patrz `meta.note`). Dla `--kind dom` morizon zwraca `area_m2`=null (pow. budynku
w `raw.house_area_m2`; teren uzupełni ingest).
**Jeśli `include_homes: true`** — dla każdej lokalizacji uruchom DODATKOWO te same skrypty z `--kind dom`
(obejmuje domy, siedliska i gospodarstwa). Uwaga: przy `--kind dom` parametry `--area-min/--area-max`
filtrują **powierzchnię działki/terenu** (nie powierzchnię domu), więc podaj te same wartości co dla działek;
w zwróconych rekordach `area_m2` to teren, a powierzchnia samego domu jest w `raw.house_area_m2`.
```
PYTHONIOENCODING=utf-8 python scripts/scrape_olx.py     --location "Walim" --kind dom --distance 15 --area-min 3000 --price-max 700000 --max 60 > /tmp/olx_dom.json
PYTHONIOENCODING=utf-8 python scripts/scrape_otodom.py  --location "Walim" --kind dom --distance 15 --area-min 3000 --price-max 700000 --max 60 > /tmp/oto_dom.json
PYTHONIOENCODING=utf-8 python scripts/scrape_morizon.py --location "Walim" --kind dom --max 60 > /tmp/mor_dom.json
```
Listing to **twarde filtrowanie** — ufaj parametrom portalu (cena/pow./lokalizacja). Połącz `listings` ze
wszystkich wyników i **odrzuć duplikaty względem JUŻ ZNANYCH** — porównaj `source`+`source_id` z wynikiem
`manage_listing.py known-sources` (obejmuje i aktywne `listings/`, i **skasowane `listings/deleted/`**).
Dzięki temu oferta raz odrzucona NIE wraca przez ingest. Zbierz świeżych kandydatów (z polem `url`) do
`/tmp/candidates.json` (tablica rekordów). Zaraportuj: ile znaleziono, ile nowych, ile pominięto jako znane
(w tym skasowane). Jeśli skrypt zwróci `meta.error` — zaznacz to i kontynuuj z pozostałymi źródłami.

## Krok 1b: Źródło — grupy Facebook (gdy włączone i są zarejestrowane grupy)
Grupy FB nie mają filtrów po stronie portalu, mieszają oferty z całej Polski, a posty to **wolny tekst**.
Dlatego: **czytanie nowych postów jest deterministyczne (skrypt)**, a **wstępne dopasowanie robi agent**
(odpowiednik twardego filtra portali, którego na surowym poście zrobić się nie da). Pomiń ten krok, jeśli
uwagi mówią „bez FB" albo nie ma żadnej `enabled` grupy.

Lista grup i znaczniki: `properties/facebook_groups.json` (zarządza `scripts/fb_groups.py` / `scrape_facebook.py`).
Sprawdź, które grupy są `enabled` (np. `manage`/`get-group` lub odczyt JSON). **Dla KAŻDEJ grupy osobny agent
`general-purpose`, równolegle** (ochrona kontekstu — surowy szum FB zostaje w agencie). Każdemu agentowi zleć:

1. **Skan (deterministyczny):**
   `PYTHONIOENCODING=utf-8 python scripts/scrape_facebook.py --scan --group <id> --max-posts 40`
   → JSON `{meta:{scanned_ids[], name, error?}, listings:[rekordy source=facebook]}`. Czytane są tylko posty
   spoza `seen_post_ids` (dedup po stronie skryptu). Jeśli `meta.error` (np. „sesja wygasła — uruchom --login")
   — zwróć ten błąd i NIE commituj; główny skill ma to zaraportować (FB nie wywala reszty wyszukiwania).
2. **Wstępne dopasowanie (LLM, w agencie):** dla każdego postu z `listings` wyciągnij z `description`:
   `location.city`, `area_m2`, `price`, `kind` (dzialka/dom), `plot_type` — i uzupełnij rekord. Odrzuć
   oczywiste pudła: inny region niż `criteria.locations`, to nie działka/dom (usługa, sprzęt, „szukam",
   reklama, pośrednik masowy). **Brak ceny/powierzchni NIE jest powodem odrzucenia** (weryfikuje ocena).
3. **(deterministycznie) prześwietl** wzbogacone rekordy przez `prescreen_candidates.py` (zapisz je do pliku
   i `--candidates-file`) — odsiewa geo/area/price/kategoria + `znana` (dedup z `listings/`+`deleted/`).
   Współrzędne uzupełni geokoder (po `location.city`), więc filtr geo zadziała.
4. **Z agenta wychodzą TYLKO rokujące rekordy** (`kept`, jako JSON) **oraz** `meta.scanned_ids` i `meta.name`
   grupy (potrzebne do commitu). To wszystko — agent nie ingestuje i nie ocenia.

Rokujące rekordy FB dołącz do puli kandydatów do **Kroku 3** (ingest). `scanned_ids` każdej grupy zachowaj do
**commitu** (koniec Kroku 5).

## Krok 2: Pre-screen potencjału (TANIO, na danych z listingu) — PRZED ingestem
**Nie zczytuj pełnych kart dla wszystkich** — najpierw odsiej pudła na podstawie listingu, żeby nie tworzyć
śmieci w bazie. Uruchom deterministyczny filtr:
```
PYTHONIOENCODING=utf-8 python scripts/prescreen_candidates.py --candidates-file /tmp/candidates.json --max-dist-km 50 > /tmp/prescreen.json
```
Odrzuca: **znana** (już w `listings/` LUB `listings/deleted/` — twardy dedup, oferta raz skasowana/dodana
NIE wraca, niezależnie od kroku 1), **geo** (za daleko od lokalizacji docelowych), **area** (< `area_min`),
**price** (> `price_max`), **kategoria** (ROD/przemysł/usługi/udział). Z pola `kept` weź kandydatów do
dalszego etapu; **zaraportuj `meta.dropped`** (ile i z jakiego powodu — bez cichych
limitów). Tylko te `kept` przechodzą dalej. (Opcjonalnie, dla pól wątpliwych co do dopasowania jakościowego,
możesz dodatkowo zlecić szybki triage `properties-eval` na chudych danych — ale brak danych o must-have NIE
jest powodem odrzucenia na tym etapie; to weryfikuje się dopiero po ingeście.)

## Krok 3: Ingest pełnych kart — TYLKO dla rokujących (skill `properties-ingest`, agenci `general-purpose`)
**Ścieżka portali (z `kept` Kroku 2):** zczytaj pełną kartę oferty do `.md`. Podziel linki na partie
po ~10–15 i **uruchom równolegle agentów `general-purpose`** (`subagent_type: general-purpose`), każdemu
zlecając skill **`properties-ingest`** na jednej partii linków (`--added-by search`). Ingest zapisze pełne
dane + galerię do `properties/listings/*.md` i zwróci `{url, id, created, photos, error}`. Zbierz `id`;
pozycje z `error` wymień osobno. Pobieranie kart trzymaj w agentach (ochrona kontekstu).

**Ścieżka grup FB (z `kept` Kroku 1b):** post FB nie ma osobnej „karty" do doczytania (pełną treść mamy już
ze skanu), więc ingest idzie z **gotowych rekordów**, pomijając Krok 2 (te rekordy zostały już prześwietlone
w Kroku 1b):
```
PYTHONIOENCODING=utf-8 python scripts/ingest_listing.py --records-file <plik_z_rokującymi_rekordami_FB>.json --added-by search
```
Zapisze je do `.md` z `source_type: facebook` + pobierze zdjęcia (fbcdn bywa tokenizowany — przy niepowodzeniu
zostają zdalne `images[]`; to akceptowalny degrade). Zbierz `id` tak samo jak dla portali.

## Krok 4: Ocena na pełnych danych (skill `properties-eval` przez agenta `general-purpose`, partiami)
Dla zingestowanych `id` pobierz **pełne rekordy z `.md`** (`manage_listing.py get --id <id>` — bierz
`frontmatter` + sekcje treści; tu jest komplet z karty). Podziel na partie ~15 i dla każdej **uruchom agenta
`general-purpose`**, który wywoła skill `properties-eval` (przez narzędzie Skill), przekazując: OPIS
poszukiwanej działki + **AKCENTY JAKOŚCIOWE z Kroku wejściowego (pkt C), jeśli były** (dosłownie, jako
dodatkowy nacisk na `score`/`reason`) + partię pełnych rekordów. Skill zwróci
`{source, source_id, score, verdict, reason, flags}`. Nie oceniaj sam w głównym kontekście. Scal oceny po
`(source, source_id)` → `id`.

> **W trybie PRZEOCEŃ ISTNIEJĄCE** rekordy do oceny bierz z `listings/` (`manage_listing.py list` →
> `get --id`), nie z ingestu — żadnego Kroku 1–3. Po ocenie idź do Kroku 5 **tylko ścieżką „istniejące":
> zapis `score` + `## Historia` + sekcja oceny, BEZ zmiany statusu.**

## Krok 5: Zapis oceny i status wg WERDYKTU (tylko NOWE oferty z wyszukiwania)
Ingest (Krok 3) już zapisał kandydatów do `.md` (pełne dane + galeria) — tu zostaje zapis oceny i status.
**Reguła dotyczy WYŁĄCZNIE nowo zingestowanych ofert** (dedup z Kroku 1/pre-screenu gwarantuje, że to nowe;
istniejących wyszukiwanie NIE dotyka).

Dla **każdej** nowej oferty zapisz ocenę (`score` + sekcja), potem ustaw status wg **werdyktu** z `properties-eval`:
```
PYTHONIOENCODING=utf-8 python scripts/manage_listing.py set --id <id> --field score --value <score>
# plik z treścią: "**Ocena: <score>/100 — <werdykt>** (wyszukiwanie <data>)\n\n<reason>"
PYTHONIOENCODING=utf-8 python scripts/manage_listing.py set-section --id <id> --header "Ocena dopasowania" --text-file <plik>
```
**Werdykt → status** (o losie decyduje werdykt, NIE sam próg liczbowy):
- **`odrzucone`** → `manage_listing.py delete --id <id>` (do `listings/deleted/`; twardy dedup, wraca tylko ręcznie).
- **`do-weryfikacji`** → `status: active` (domyślny po ingeście — zostaw; to pozycje „warto sprawdzić").
- **`dopasowane`** → `manage_listing.py set-status --id <id> --status watch` (obserwowane).

(`score_threshold` z `criteria.md` jest pomocniczy/orientacyjny — disposition robi werdykt.)
Identycznie w obu trybach. W **interaktywnym** dodatkowo pokaż ranking (tabela niżej) z linkami; użytkownik
może potem ręcznie zmienić status (np. promować do `favorite`). Wklejone przez użytkownika linki → skill
`properties-ingest` (`--added-by user`), potem ocena jak wyżej.

> **Istniejących ofert wyszukiwanie nie rusza statusu.** Jeśli kiedyś re-ocena dotknie istniejącej oferty:
> zaktualizuj `score`, **dopisz nowy wynik do `## Historia`** (`manage_listing.py log`), zaktualizuj sekcję
> oceny (zmienia to `date_updated`) — ale **statusu NIE zmieniaj** (to decyzja użytkownika).

## Krok 5b: Dedup zabezpieczający (po dopisaniu nowych ofert)
Po ingeście i dyspozycji uruchom doktora deduplikacji — łapie bliźniaki, które mogłyby powstać mimo
dedupu na wejściu (np. Otodom nadaje tej samej ofercie różny `source_id`, albo kolizja z przywracaniem
z `deleted/`). Zostawia najbogatszy rekord, resztę przenosi do `deleted/`:
```
PYTHONIOENCODING=utf-8 python scripts/manage_listing.py dedupe --apply
```
Zaraportuj `groups` (ile par scalono) i co skasowano. Pomiń w trybie PRZEOCEŃ ISTNIEJĄCE (nie dopisujesz
nowych, więc nie ma czego deduplikować).

## Krok 6: Commit znaczników grup FB (gdy był Krok 1b)
Dopiero **po** ingeście i dyspozycji przesuń znacznik „ostatnio przeczytane" KAŻDEJ skanowanej grupy — żeby
te same posty (także odrzucone) nie wracały w kolejnym skanie. Dla każdej grupy zapisz jej `meta.scanned_ids`
(z Kroku 1b) do pliku i wywołaj:
```
PYTHONIOENCODING=utf-8 python scripts/scrape_facebook.py --commit --group <id> --scanned-ids-file <ids.json>
```
**Nie commituj grupy, której skan zwrócił `meta.error`** (sesja/parsowanie) — wtedy posty mają być
przeczytane ponownie następnym razem. Zaraportuj, które grupy skomitowano, a które pominięto z błędem.

## Output

Najpierw podsumowanie:
```
WYSZUKIWANIE DZIAŁEK (tryb: …)
Lokalizacje: …    Kryteria: pow. …–… m², cena ≤ …, próg score …
Znaleziono: N   Nowych (po dedup): M   Dodano: K
```
Następnie tabela rankingu (sort malejąco po score). Kolumna `typ` = działka/dom; dla domu `pow.` oznacza
powierzchnię działki (teren), a powierzchnię domu podaj w nawiasie, jeśli dostępna w `raw.house_area_m2`:
```
| # | score | ocena | typ | pow. (teren) | cena | zł/m² | miejscowość | źródło | link |
|---|-------|-------|-----|--------------|------|-------|-------------|--------|------|
```
**Kolumna `link` jest obowiązkowa dla każdej oferty z ogłoszenia** — wstaw klikalny markdown `[link](URL)`
z pola `url` rekordu (OLX/Otodom/Morizon/gethome; dla `źródło: facebook` → link do postu w grupie). Nigdy
nie pokazuj oferty z ogłoszeniem bez linku do ogłoszenia.
Jeśli `url` chwilowo niedostępny (np. pozycja tylko po `source_id`), odtwórz go przed prezentacją. Dla
pozycji `source_type: geoportal` (bez ogłoszenia) w kolumnie `link` wpisz „—".

W trybie interaktywnym zakończ pytaniem, które dodać. W autonomicznym — listą dodanych `id`
i krótką notą o pominiętych.

## Zasady
- **Rozdział ról**: ten skill listuje i orkiestruje; ocenę robi skill `properties-eval` (uruchamiany przez
  agenta `general-purpose`); zapis robi `properties-list-manage`. Nie powielaj logiki zapisu/oceny.
- **Dedup przed oceną** — nie oceniaj ponownie pozycji już na liście (oszczędność).
- **Budżet**: przy wielu lokalizacjach ogranicz `--max` na źródło, by nie przeciążać; raportuj, jeśli
  obcinasz wyniki (żadnych cichych limitów).
- **Nie zgaduj na korzyść** przy braku danych o must-have — niech agent obniży score i oznaczy „do weryfikacji".
- **Zgłaszaj błędy źródeł** wprost (np. blokada Otodom → zostaje OLX + gethome).
- **Zawsze z linkiem do ogłoszenia**: za każdym razem, gdy prezentujesz oferty pochodzące z ogłoszeń
  (ranking, podsumowanie, lista, pojedyncza oferta), podawaj klikalny link do ogłoszenia. Bez wyjątków.
