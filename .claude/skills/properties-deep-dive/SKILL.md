---
name: properties-deep-dive
description: "Pogłębiona analiza działki/oferty: geoportal (nr działki, przeznaczenie wstępne), NMT (wysokość, nachylenie, ekspozycja stoku), odległości do must-have (kolej, sklep, szpital, woda) z OSM, analiza zdjęć ogłoszenia (widok/otulina/stok oraz odczyt numeru działki z mapki/planu, jeśli widoczny) i wskazówki do ręcznej weryfikacji MPZP/transakcji/właściciela. Zapisuje wynik do sekcji ## Analiza pogłębiona; NIE zmienia statusu oferty (to decyzja użytkownika)."
when_to_use: "pogłębiona analiza działki, sprawdź działkę w geoportalu, analiza terenu, czy działka budowlana, nachylenie i ekspozycja, odległości do udogodnień, deep dive działki, zweryfikuj ofertę"
argument-hint: "<ID listingu lub URL ogłoszenia>"
allowed-tools: Bash, Read, Glob
model: sonnet
---

# properties-deep-dive — pogłębiona analiza działki

Bierzesz JEDNĄ ofertę (po `id` listingu albo URL) i robisz analizę, której scoring tekstowy
(`properties-eval`) nie obejmuje: geoportal, ukształtowanie terenu, realne odległości oraz **oględziny zdjęć**.
**Nie zmieniasz statusu oferty** — favorite/obserwowane/aktywne to decyzja użytkownika (status ustawia UI). Rdzeń danych zbiera przetestowany skrypt `scripts/geo_analyze.py`
(ULDK GUGiK + NMT + OpenStreetMap); Ty **interpretujesz** wynik względem kryteriów z `properties/criteria.md`.
Komendy uruchamiaj z katalogu projektu, prefiks `PYTHONIOENCODING=utf-8`.

> **Rozdział ról**: `geo_analyze.py` i `manage_listing.py` zbierają/zapisują dane (nie oceniają);
> ocenę i rekomendację robisz Ty w tym skillu. Nie powielaj logiki scrapowania ani zapisu.

## Krok 0: Ustal cel i kryteria
- Jeśli dostałeś **URL** (nie ma jeszcze na liście) — najpierw dodaj ofertę skillem `properties-list-manage`
  (intencja „dodaj z linku"), weź zwrócone `id`.
- Wczytaj `properties/criteria.md` — sekcja must-have (progi odległości) i „Charakter działki" (do oceny zdjęć).
- Wczytaj rekord: `PYTHONIOENCODING=utf-8 python scripts/manage_listing.py get --id <id>`.
  Zanotuj `lat`, `lon`, `coords_approx`, `area_m2`, `kind`, `url`.

## Krok 1: (status — bez zmian)
**NIE zmieniaj statusu oferty.** Deep-dive tylko analizuje i dopisuje dane; o statusie (favorite/active/…)
decyduje użytkownik w UI. (W przepływie „⭐ Ulubione → deep-dive" status `favorite` jest już ustawiony przez
UI przed wywołaniem tego skilla.)

## Krok 2: Analiza terenowa (przetestowany skrypt)
**Najpierw wyłuskaj z ogłoszenia numery działek ORAZ nazwę obrębu/miejscowości (to Twoje zadanie — nie
skryptu).** Przeczytaj `description`/`title` i wypisz: (1) wszystkie jawne numery ewidencyjne (np. „działka
nr 319/5", „dz. ewid. 123/4", „nr 319/5 i 319/6"); (2) **nazwę obrębu/wsi, w której leży działka** — często
w tytule/treści (np. „w Bartnicy", „obręb Krzewina", „działka w Świerkach"). Wyłuskanie z tekstu robisz Ty
(LLM); **rozwiązanie numeru na współrzędne jest już deterministyczne** w skrypcie.

Uruchom analizę — **jeśli znalazłeś numery, podaj każdy przez `--parcel-no`, a nazwę obrębu przez
`--region-name`** (oba powtarzalne):
```
# gdy w ogłoszeniu są numery działek (przykład: 18/5 w obrębie Bartnica):
PYTHONIOENCODING=utf-8 python scripts/geo_analyze.py --id <id> --parcel-no 18/5 --region-name Bartnica > /tmp/dd_<id>.json
# kilka numerów / kilka możliwych nazw:
PYTHONIOENCODING=utf-8 python scripts/geo_analyze.py --id <id> --parcel-no 319/5 --parcel-no 319/6 --region-name "Nowa Wieś" > /tmp/dd_<id>.json
# gdy w ogłoszeniu NIE ma numerów:
PYTHONIOENCODING=utf-8 python scripts/geo_analyze.py --id <id> > /tmp/dd_<id>.json
```
**NUMER DZIAŁKI MA PIERWSZEŃSTWO NAD WSPÓŁRZĘDNYMI z portalu** (te bywają adresem agencji, nie działki).
Dlatego skrypt najpierw rozwiązuje numer **po nazwie obrębu** (`GetParcelByIdOrNr`, „<obręb> <nr>"),
walidując wynik powiatem spod współrzędnych i powierzchnią z oferty; dopiero gdy nazwa nie zadziała, próbuje
obrębu spod współrzędnych. Dlatego **zawsze podawaj `--region-name`, gdy znasz nazwę obrębu/wsi** — bez niej
skrypt użyje tylko miejscowości spod współrzędnych (a ta bywa inna niż faktyczny obręb działki, np. adres
agencji). Wynik: `parcel.confirmed=true`, `coords_orientacyjne=false`, `parcel_source="ogłoszenie+ULDK (…)"`
(nawias mówi, jak rozwiązano: po nazwie obrębu czy spod współrzędnych), `parcel_no`, `geoportal_url`,
`gmaps_url`, `region` (właściwy obręb), listę `parcels[]` (nr, id, pole, lat/lon) i
`input.position_from="geoportal (nr działki)"`. **To te współrzędne (z geoportalu) określają pozycję** —
`terrain`/`pois` liczone są już z nich, nie z punktu ogłoszenia. Gdy działka wyszła w innym obrębie niż
współrzędne, `notes` to odnotuje.

Skrypt zwraca też: `terrain` (`elevation_m`, `slope_pct`, `slope_deg`, `aspect`), `pois` (najbliższe:
`railway`, `supermarket`, `hospital`, `water` z `dist_m`), `links` i `notes`.

**ZASADA NACZELNA — współrzędne z portali są orientacyjne, DOPÓKI nie rozwiążemy numeru działki.**
Punkt z ogłoszenia (OLX/Otodom) to zwykle centroid miejscowości. Gdy skrypt rozwiązał numer
(`parcel.confirmed=true`, `coords_orientacyjne=false`) — pozycja jest z geoportalu i **pewna** (nie pisz
wtedy „współrzędne orientacyjne"). W przeciwnym razie `terrain` traktuj jako poglądowy, a **numeru działki
NIGDY nie podawaj „bo ULDK by-XY coś zwrócił"**. Numer działki wolno zapisać **tylko** gdy:
- **(a) jest wprost podany w treści ogłoszenia** (np. „działka nr 89/5", „dz. ewid. 123/4", „nr 319/5 i 319/6")
  — wyłuskujesz go z `description`/`title` i podajesz do `geo_analyze` przez `--parcel-no`. Skrypt rozwiązuje
  go w ULDK na realną geometrię (`parcel.confirmed=true`, współrzędne z geoportalu). Numer autorytatywny
  (źródło: ogłoszenie+ULDK). **To domyślny, najważniejszy przypadek — gdy w ogłoszeniu są numery, ZAWSZE
  podaj je przez `--parcel-no`.** Albo
- **(b) deep-dive potwierdził go powierzchnią** — `geo_analyze` zwraca `parcel.area_match` (porównanie pola
  geometrii z ULDK do `area_m2` z oferty, tolerancja 15%) i `parcel.confirmed_by_area`. Gdy `true` → punkt
  trafił w tę właśnie działkę, numer jest wiarygodny (źródło: ULDK+powierzchnia), albo
- **(c) jest czytelnie widoczny na zdjęciu planu/mapki geodezyjnej** z ogłoszenia (numer + zwykle obręb) —
  odczytujesz go w Kroku 3. To sprzedający pokazuje własny plan, więc numer jest autorytatywny jak z treści
  (źródło: zdjęcie). Jeśli dodatkowo zgadza się z ULDK (ten sam numer lub `area_match`) — tym pewniejszy.

**PIERWSZEŃSTWO ŹRÓDEŁ I ROZSTRZYGANIE KONFLIKTÓW (kolejność ważności):** treść ogłoszenia (a) **przed**
mapką/zdjęciem (c) **przed** samą powierzchnią (b). Gdy treść podaje numer wprost („numer działki: 365") —
**to jest numer autorytatywny, także gdy na mapce w galerii widać inny** (mapka bywa poglądowa/sąsiednia,
numer łatwo przeczytać błędnie). W razie rozbieżności treść vs mapka: **weź numer z treści**, a numer z mapki
najwyżej odnotuj jako „do sprawdzenia". **Zanim odczytasz numer z mapki, upewnij się, że przeczytałeś CAŁĄ
treść** (`description` bywał historycznie ucięty przy dodaniu z wyszukiwania — jeśli opis wygląda na obcięty,
tj. urywa się w połowie zdania/słowa, **najpierw ponów ingest** `python scripts/ingest_listing.py --url <url>`,
by pobrać pełną kartę, i dopiero potem szukaj numeru). **Kontrola powierzchnią:** jeśli `geo_analyze` zwrócił
`area_match:false` dla numeru odczytanego z mapki (pole ULDK znacząco ≠ `area_m2` z oferty) — **traktuj to jako
sygnał, że numer jest BŁĘDNY**, a nie automatycznie jako „sprzedaż części działki". „Część działki" zakładaj
tylko, gdy sama treść to mówi; inaczej odrzuć numer i szukaj właściwego (zwłaszcza numeru z treści).

W **każdym innym** przypadku (brak nr w ogłoszeniu, brak na mapce i `area_match` ≠ true) **NIE zapisuj numeru działki ani
TERYT/linku geoportalu po identyfikatorze** — bo wskazywałby cudzą parcelę. Zostają tylko jednostki
administracyjne (woj./powiat/gmina/obręb — orientacyjne, bo miejscowość jest właściwa) i adnotacja
„działka niepotwierdzona — wskaż punkt na mapie".

## Krok 3: Oględziny zdjęć (to domyka lukę scoringu)
Znajdź zdjęcia: `Glob` po `properties/photos/<id>/*` (lub z rekordu pole `photos`). Obejrzyj je
narzędziem `Read` (do ~8 najbardziej informatywnych). Oceń **wprost to, czego nie ma w opisie**:
- **Widok** — czy realnie widać góry/panoramę/dolinę, czy zasłonięte; daleki czy bliski.
- **Otulina leśna** — czy działka ma las/zadrzewienie wokół, czy goła (kluczowe rozróżnienie z kryteriów).
- **Ekspozycja / stok** — czy teren wznosi się/opada, czy płaski (zestaw z `terrain.slope_pct`/`aspect`).
- **Charakter otoczenia** — środek osiedla vs na uboczu; sąsiedztwo, linie energetyczne, zabudowa.
- **Dojazd** — droga utwardzona/asfalt vs polna; bramy/służebność jeśli widać.
- **Numer działki / mapka geodezyjna** — jeśli któreś zdjęcie to plan, szkic geodezyjny, mapa ewidencyjna
  lub wypis (często wskazuje je pole `map_photo`), **odczytaj z niego numer(y) działki** (np. „123/4"),
  **obręb** i ew. powierzchnię. To domyka największą lukę: numer bywa właśnie na mapce, a nie w tekście.
  Zapisz dosłownie, co odczytałeś (i z którego zdjęcia), do wykorzystania w Kroku 6.
Jeśli brak zdjęć — zaznacz „brak zdjęć do oceny wizualnej" i nie zgaduj.

## Krok 4: Zestaw odległości z progami must-have
Porównaj `pois[*].dist_m` z progami z kryteriów (orientacyjne przeliczenie czasu na dystans):
| Must-have | Próg (z kryteriów) | ✓ ok | ⚠ granicznie | ✗ słabo |
|-----------|--------------------|------|--------------|---------|
| Stacja kolejowa | ~15 min rowerem | ≤ 4 km | 4–8 km | > 8 km |
| Sklep (Dino/Biedronka/Lidl) | ~10 min autem | ≤ 6 km | 6–10 km | > 10 km |
| Szpital | ~30 min autem | ≤ 25 km | 25–40 km | > 40 km |
| Rekreacja wodna | ~20–25 min e-rowerem | ≤ 10 km | 10–15 km | > 15 km |

Stok narciarski (~1 h autem) zwykle nie wychodzi z POI — odnotuj „do ręcznej weryfikacji", jeśli brak.
Odległości liczone są z pozycji efektywnej: gdy numer rozwiązany (`position_from="geoportal (nr działki)"`)
— z realnej działki; w przeciwnym razie od centroidu miejscowości (±kilka km) — wtedy to zaznacz.

## Krok 5: Ręczna weryfikacja (czego NIE da się automatycznie)
Z `links` przenieś do wyniku gotowe odnośniki i zadania:
- **Przeznaczenie (MPZP/WZ)** — `links.geoportal` + `mpzp_hint` (czy budowlana/rolna/leśna, plan gminy).
- **Transakcje (RCiWN)** — `rcwin_hint` (warstwa cen transakcyjnych — zwykle wymaga uprawnień).
- **Właściciel (KW)** — `ekw_hint` (potrzebny nr KW — od sprzedającego/starostwa; brak otwartego API).
Wypisz je jako konkretne „następne kroki", nie jako ogólnik.

## Krok 6: Zapis wyniku i aktualizacja rekordu
Złóż sekcję Markdown (format poniżej) i zapisz:
```
PYTHONIOENCODING=utf-8 python scripts/manage_listing.py set-section --id <id> --header "Analiza pogłębiona" --text-file /tmp/dd_section_<id>.md
```
Zapisz blok `parcel` **wg reguły wiarygodności** (patrz „ZASADA NACZELNA"). Złóż obiekt JSON:
- Zawsze: `voivodeship`, `county`, `commune`, `region` (z `geo_analyze`) oraz **`gmaps_url`** z `geo_analyze`
  (link do Google Maps — jest zawsze, gdy znamy współrzędne; orientacyjny lub pewny).
- **Gdy `geo_analyze` rozwiązał numer (`parcel.confirmed=true`, `position_from="geoportal (nr działki)"`)**
  — to główny przypadek: **weź obiekt `parcel` z `geo_analyze` w całości** (`id`, `parcel_no`, `parcels[]`,
  `geoportal_url`, `gmaps_url`, `area_m2_geom`, `coords_orientacyjne: false`, `parcel_source: "ogłoszenie+ULDK"`).
  Współrzędne są PEWNE (z geoportalu).
- Inne drogi potwierdzenia (gdy nie podano numeru wprost):
  - `geo_analyze` zwrócił `confirmed_by_area: true` → weź `id`/`parcel_no`/`obreb_number`/`geoportal_url`
    z `geo_analyze`, `confirmed: true`, `parcel_source: "ULDK+powierzchnia"`;
  - **numer odczytany ze zdjęcia planu/mapki** (Krok 3) → jeśli masz obręb, dopytaj skrypt ponownie z
    `--parcel-no <numer>` (rozwiąże jak wyżej); inaczej zapisz `parcel_no` = numer, `confirmed: true`,
    `parcel_source: "zdjęcie (mapka)"`. Rozbieżność ze zdjęciem vs ULDK — zaufaj zdjęciu, dopisz notę.
- **W innym wypadku**: NIE dawaj `parcel_no`/`id`/`geoportal_url`; ustaw `confirmed: false`,
  `coords_orientacyjne: true`, `parcel_source: "niepotwierdzona"` (ale `gmaps_url` i tak dołącz — punkt orientacyjny).
```
PYTHONIOENCODING=utf-8 python scripts/manage_listing.py set --id <id> --field parcel --value '<złożony JSON wg reguły>'
PYTHONIOENCODING=utf-8 python scripts/manage_listing.py set --id <id> --field terrain.slope_pct --value <liczba>
PYTHONIOENCODING=utf-8 python scripts/manage_listing.py set --id <id> --field terrain.aspect    --value "<N/S/...>"
PYTHONIOENCODING=utf-8 python scripts/manage_listing.py set --id <id> --field deep_dive.date     --value "<RRRR-MM-DD>"
```
W sekcji „## Analiza pogłębiona": gdy `coords_orientacyjne=false` (numer rozwiązany) napisz „pozycja z
geoportalu — współrzędne pewne" i podaj `geoportal_url` + `gmaps_url`. Gdy `confirmed:false` napisz wprost
„nr działki niepotwierdzony — wskaż punkt na mapie lub podaj nr z ogłoszenia" i zaznacz, że współrzędne są
orientacyjne (centroid miejscowości).
Gdy działka potwierdzona, link do geoportalu wygenerujesz też: `python scripts/geoportal_link.py --id <id>`.
Zapisz też **wpis do historii** (uruchomienia mają być widoczne, także przy powtórnym deep-dive):
```
PYTHONIOENCODING=utf-8 python scripts/manage_listing.py log --id <id> --text "deep-dive uruchomiony (geo+zdjęcia)"
```
**Status pozostaw bez zmian** (deep-dive nie rusza statusu). Jeśli pogłębiona analiza zmienia ocenę,
zaktualizuj `score` (`set --field score`) i **dopisz nowy wynik do historii**
(`log --text "po deep-dive: score <nowy> (było <stary>)"`) — to bumpuje `date_updated`; statusu NIE zmieniaj.
Pól geoportalowych przeznaczenia nie zgaduj — wpisuj `mpzp.status` dopiero po ręcznym potwierdzeniu.
Jeśli z karty/opisu jednoznacznie wynika **rodzaj działki**, ustaw/popraw go (heurystyka ingestu bywa zgrubna):
`manage_listing.py set --id <id> --field land_type --value <rolna|siedliskowa|budowlana>`.

## Output (do sekcji ## Analiza pogłębiona + zwięzłe podsumowanie w czacie)
Sekcja zapisywana do pliku (Markdown):
```
**Działka (ULDK):** nr <…>, gmina <…>, powiat <…>, obręb <…>  [pole geom. ~<…> m²]
**Teren (NMT):** <…> m n.p.m., nachylenie <…>% (<…>°), ekspozycja <…>
**Odległości:** kolej <…> (<dist>), sklep <…> (<dist>), szpital <…> (<dist>), woda <…> (<dist>)
**Zdjęcia:** widok=<…>, otulina leśna=<…>, ekspozycja=<…>, otoczenie=<…>, nr działki z mapki=<… / brak>
**Do weryfikacji ręcznej:** MPZP → <link> · transakcje → <…> · właściciel/KW → <…>
**Linki:** geoportal <…> · mapa <…>
**Werdykt po pogłębieniu:** <potwierdza/obniża/podnosi ocenę wstępną> — <1–2 zdania>
> Zastrzeżenie: współrzędne <dokładne|przybliżone (centroid miejscowości)> — <konsekwencje>.
```
W czacie zwróć **skróconą** wersję (4–6 linijek) + link do ogłoszenia i `id`. Zawsze podawaj link do ogłoszenia.

## Zasady
- **Budżet**: ~3–4 wywołania skryptów + ≤8 zdjęć. Po przekroczeniu — zwróć wynik częściowy z adnotacją,
  co pominięto (np. „POI niedostępne — Overpass rate-limit").
- **Nie zgaduj na korzyść**: brak danych (zwłaszcza przy `coords_approx`) → oznacz „do weryfikacji",
  nie podnoś werdyktu. Pole geom. mocno ≠ powierzchni z oferty → ostrzeż o trafieniu w inną parcelę.
- **Zgłaszaj błędy źródeł wprost** (ULDK/NMT/Overpass) — sekcja `notes` z wyniku skryptu idzie do raportu.
- **Zawsze z linkiem do ogłoszenia** przy prezentacji oferty.
- **Zapis tylko przez `manage_listing.py`** — nigdy ręcznie w plikach `.md`.
