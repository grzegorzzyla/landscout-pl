---
# Parametry wyszukiwania (czytane przez properties-search i scrapery)
transaction: sale            # sale | rent
property_type: dzialka       # podstawowy typ; gdy include_homes=true, search szuka też domów (--kind dom)
include_homes: true          # true = oprócz działek przeszukuj też domy/siedliska/gospodarstwa (scrapery: --kind dom)
locations:                   # góry do ~1,5 h jazdy z Wrocławia; każda lokalizacja przeszukiwana osobno z własnym promieniem
  - { name: "Walim", distance_km: 12 }            # rdzeń: Zagórze Śląskie, Niedźwiedzica, Olszyniec, Glinno, Rzeczka
  - { name: "Głuszyca", distance_km: 10 }         # sąsiedztwo Walimia / Góry Sowie
  - { name: "Bardo", distance_km: 12 }            # powiat ząbkowicki/kłodzki
  - { name: "Kłodzko", distance_km: 15 }          # powiat kłodzki i okolice
area_min: 3000               # m² — twarde minimum (ale nie w środku osiedla)
area_max: null               # bez górnej granicy — im więcej tym lepiej (wymarzone 5000–10000)
price_min: null              # PLN (null = brak dolnego limitu)
price_max: 700000            # PLN — szeroka sieć; cel na DZIAŁKĘ docelową to 300–400k, wyżej tylko duży teren z potencjałem podziału (patrz opis)
score_threshold: 45          # próg pomocniczy (eksperymentalnie 45); o losie NOWEJ oferty decyduje WERDYKT
                             # eval: dopasowane→obserwowane, do-weryfikacji→aktywne, odrzucone→deleted
---

# Opis poszukiwanej działki

> Ten opis jest używany przez ocenę jakościową (LLM) do nadania każdemu ogłoszeniu score 0–100.
> Decyduje, co trafia na listę — jest ważniejszy niż surowe parametry z frontmattera.

## Cel
Działka pod dom **całoroczny w górach** — przeprowadzka na stałe, nie drugi dom weekendowy.
Horyzont użytkowania ~**15 lat**. Ma być realnym miejscem do życia na co dzień.

Teren w **górach, do ~1,5 h jazdy samochodem z Wrocławia**. Rdzeń zainteresowania: **gmina Walim**
(Zagórze Śląskie, Niedźwiedzica, Walim, Góry Sowie). Otwarci też na **powiat kłodzki / ząbkowicki**
(Bardo i okolice, Kłodzko).

## Charakter działki — to decyduje (najważniejsze)
Ideał: **działka wysoko na stoku, z widokiem na góry, ale w leśnej otulinie** — albo wprost **działka leśna
z możliwością wycięcia kilku drzew** pod dom i odsłonięcie widoku.

Dwa typowe, gorsze warianty, które chcemy odróżnić:
- **z widokiem, ale goła** (bez otuliny, bez zieleni) — słabiej;
- **w lesie, ale bez widoku** (np. polana w środku lasu) — słabo: jeśli nie ma widoku ani ekspozycji
  górskiej, to po co jechać w góry — pod Wrocławiem na płaskim znajdzie się to samo taniej.

Im realniej oferta zbliża się do „wysoko na stoku + widok + otulina leśna", tym wyżej oceniaj.

## Powierzchnia i forma własności
- **Minimum 3000 m²** (ale nie wciśnięte w środek osiedla). Wymarzone **5000–10000 m²**, górnej granicy brak —
  **im więcej tym lepiej**.
- Może być **łączenie 2–3 sąsiednich działek** w jeden teren.
- Dopuszczalne **działki rolne i leśne** (potencjał: odrolnienie / siedlisko / zabudowa zagrodowa) — nie musi
  być od razu budowlana z MPZP.
- **Większy teren z zamiarem podziału** i odsprzedaży połowy jest OK — to uzasadnia wyższą cenę zakupu.

## Infrastruktura (must-have — sprawdzane na etapie weryfikacji)
- **Stacja kolejowa** w zasięgu **~15 min rowerem**.
- **Szpital** w zasięgu **~30 min samochodem**.
- **Sklep typu Dino / Biedronka / Lidl** w zasięgu **~10 min**.
- **Rekreacja wodna** (jezioro/zalew/kąpielisko) **~20–25 min rowerem elektrycznym**.
- **Stok narciarski** w zasięgu **~1 h samochodem**.

> Ogłoszenie zwykle nie poda tych odległości wprost — jeśli brak danych, **nie zgaduj na korzyść**:
> oznacz „do weryfikacji" zamiast zawyżać score.

## Dom całoroczny — wymagania praktyczne
- **Media całoroczne** lub realna możliwość ich doprowadzenia: prąd; woda (studnia/wodociąg); ogrzewanie.
- **Dojazd drogą publiczną przejezdną zimą** (nie służebność przez cudzą działkę, nie polna ścieżka bez
  utrzymania zimowego).
- Dostęp do **internetu** (światłowód / dobry zasięg) — istotny dla pracy zdalnej.

## Dyskwalifikujące (niska ocena / odrzucenie)
- **Środek osiedla / gęstej zabudowy** — brak przestrzeni, prywatności i ekspozycji.
- **Brak dojazdu** drogą publiczną; teren **osuwiskowy** lub **zalewowy**.
- Brak jakiejkolwiek ekspozycji górskiej **i** brak walorów leśnych jednocześnie (płaska, bez widoku, bez lasu).
- Działka uniemożliwiająca sensowne posadowienie domu (skrajnie wąska, skalna ściana itp.).

## Mile widziane (podnoszą ocenę)
- Sprzedaż **od właściciela** (mniej prowizji).
- Sąsiedztwo strefy zabudowy w projektowanym planie ogólnym gminy (**SO/SJ** obok) — działka **na skraju
  osiedla** jest OK, bliskość infrastruktury bez utraty widoku.
- Rozsądna cena za m² na tle okolicy; dobry stan prawny (KW, dostęp, brak współwłasności do rozwikłania).
- Stary **dom lub gospodarstwo** do remontu na dużym, widokowym terenie.

## Uwagi
- **Domy i gospodarstwa**: są w grze równorzędnie z działkami (`include_homes: true`). Scrapery obsługują je
  przez `--kind dom` (OLX/Otodom/gethome) — `properties-search` uruchamia ten wariant automatycznie. Dla domów
  `area_m2` to powierzchnia **działki/terenu** (pow. budynku w `raw.house_area_m2`). Pojedyncze oferty można
  też dodać z wklejonego linku przez `properties-list-manage` (typ rozpoznawany automatycznie).
- Działki **wytypowane samodzielnie z geoportalu** (bez ogłoszenia) dodawane są ręcznie przez
  `properties-list-manage` z `source_type: geoportal`.
- `price_max` celowo ustawione szeroko (700k) dla recall — **docelowy budżet na samą działkę to 300–400 tys.**;
  wyższe kwoty uzasadnione **wyłącznie** dużym terenem z realnym potencjałem podziału i odsprzedaży połowy.
