---
# Parametry wyszukiwania (czytane przez properties-search i scrapery)
transaction: sale            # sale | rent
property_type: dzialka       # podstawowy typ; gdy include_homes=true, search szuka też domów (--kind dom)
include_homes: true          # true = oprócz działek przeszukuj też domy/siedliska/gospodarstwa (scrapery: --kind dom)
locations:                   # trzy równorzędne regiony; każda lokalizacja przeszukiwana osobno z własnym promieniem
  - { name: "Rozprza", distance_km: 12 }                # łódzkie — CAŁA gmina Rozprza (promień od siedziby gminy)
  - { name: "Sulejów", distance_km: 15 }                # łódzkie — CAŁA gmina Sulejów (Zalew Sulejowski, lasy spalskie)
  - { name: "Wleń", distance_km: 20 }                   # Dolny Śląsk — pogórze izerskie/kaczawskie
  - { name: "Klecza", distance_km: 12 }                 # Dolny Śląsk — okolice Wlenia
  - { name: "Ełk", distance_km: 25 }                    # warmińsko-mazurskie — rozważane wcześniej, nadal w grze
  - { name: "Dukla", distance_km: 25 }                  # podkarpackie — Beskid Niski (spadź ChNP, lipa, akacja); najtańsza ziemia
  - { name: "Bielsk Podlaski", distance_km: 25 }        # podlaskie — zagłębie gryki, najciemniejsze niebo w PL
  - { name: "Świerzawa", distance_km: 15 }              # dolnośląskie — Góry Kaczawskie; rozszerza krąg Wlenia na wschód
area_min: 10000              # m² = 1 ha — twarde minimum; cel to POWIĘKSZENIE istniejącego areału
area_max: null               # bez górnej granicy — im więcej tym lepiej (wymarzone 2–5 ha i więcej)
price_min: null              # PLN (null = brak dolnego limitu)
price_max: 500000            # PLN — górny budżet na całość transakcji
price_per_m2_max_rolna: 5    # zł/m² — DOCELOWA cena ziemi ROLNEJ (patrz opis). UWAGA: parametr czytany przez
                             # OCENĘ (LLM), nie przez pre-screen — pre-screen filtruje tylko po price_max
adresowo_searches:           # adresowo.pl — gotowe adresy wyszukiwań (opcjonalne, patrz README)
                             # Klucz = nazwa lokalizacji z listy `locations` powyżej.
                             # Adres kopiujesz z paska przeglądarki po ustawieniu filtrów na adresowo.pl
                             # (Typ działki, Źródło: Bezpośrednie, Pow. działki, Cena/m², wybór gmin).
                             # Bez wpisu scraper sam złoży adres dla województwa danej lokalizacji.
  Rozprza: "https://adresowo.pl/f/dzialki/182845_182930_182979_183076_183145_183213_183415_183468_183579_183862_184007/fz3z4z5z6z7z8zb"
  Sulejów: "https://adresowo.pl/f/dzialki/182845_182930_182979_183076_183145_183213_183415_183468_183579_183862_184007/fz3z4z5z6z7z8zb"
score_threshold: 45          # próg pomocniczy; o losie NOWEJ oferty decyduje WERDYKT
                             # eval: dopasowane→obserwowane, do-weryfikacji→aktywne, odrzucone→deleted
---

# Opis poszukiwanej nieruchomości

> Ten opis jest używany przez ocenę jakościową (LLM) do nadania każdemu ogłoszeniu score 0–100.
> Decyduje, co trafia na listę — jest ważniejszy niż surowe parametry z frontmattera.

## Cel (to jest sedno)
**Powiększenie areału rolnego.** Do posiadanego, niewielkiego areału potrzeba realnie więcej ziemi —
takiej, która **pracuje**. To nie jest zakup rekreacyjny ani lokata.

Drugi, równoległy cel: **przenieść pasiekę** (na razie małą) i mieć ją gdzie rozwijać — łącznie z możliwością
**obsiania własnego terenu roślinami miododajnymi**.

Docelowo także **dom / miejsce do życia na co dzień**, ale to nie jest warunek wejścia — ziemia jest ważniejsza
niż gotowa działka budowlana z pozwoleniem. Horyzont użytkowania ~**15 lat**.

## Pożytki pszczele — pierwszy filar oceny
Najwyżej oceniaj tereny, gdzie pszczoły mają z czego zbierać — na działce i **w promieniu lotu (~3 km)**:
- **rzepak, gryka, facelia, gorczyca** — uprawy towarowe dające pożytek;
- **łąki kwietne, nieużytki kwitnące, miedze, ugory**;
- **las** (spadź, akacja/robinia, lipa, wierzba, wrzos) — zwłaszcza liściasty i obrzeża lasu;
- **sady, zadrzewienia śródpolne, aleje lipowe**.

Sygnały in minus dla pasieki:
- **monokultura zbożowa / kukurydza bez kwitnących sąsiadów** — pustynia pożytkowa;
- **wielkoobszarowe rolnictwo intensywnie opryskiwane** (ryzyko podtruć) — rzepak jest pożytkiem, ale
  gdy dookoła jest wyłącznie wielkopolowa chemia, to minus, nie plus;
- brak jakiejkolwiek zieleni kwitnącej w okolicy.

## Cisza, przestrzeń, brak uciążliwości — drugi filar oceny
**Cisza jest kryterium priorytetowym, nie dodatkiem.** Sąsiedztwo czynnej linii kolejowej i drogi
krajowej jednocześnie jest dokładnie tym układem, którego chcemy uniknąć. Dlatego:
- działka powinna być **z dala od czynnej linii kolejowej** (orientacyjnie min. ~1,5–2 km);
- **z dala od drogi ekspresowej/krajowej i ruchliwej wojewódzkiej**;
- z dala od tartaku, kopalni kruszywa, wiatraków przy zabudowie, torów motocrossowych.

Dalej — **brak uciążliwości** w sąsiedztwie:
- **ciężki przemysł**, zakłady emisyjne, składowiska, wyrobiska, oczyszczalnia, biogazownia;
- **ferma przemysłowa: chlewnia, kurnik, obora** — odór i muchy przekreślają miejsce do życia;
- tereny **skażone / poprzemysłowe**;
- **zanieczyszczenie światłem** — ciemne niebo jest wartością, łuna wielkiego miasta lub zakładu to minus.

Do tego: **dużo przestrzeni**. Nie chodzi o metry w tabelce, tylko o brak ścisku — sąsiad nie pod oknem,
otwarty horyzont, własny teren dookoła.

## Czego ogłoszenie NIE powie — sprawdzaj otoczenie na mapie
Sprzedający nigdy nie napisze, że obok jest cmentarz, ferma albo tory. Opis milczy o wadach z definicji.
Dlatego przy ofercie, która wygląda dobrze „na papierze", **traktuj brak informacji o otoczeniu jako lukę
do sprawdzenia, nie jako brak problemu** — i oznaczaj „do weryfikacji" zamiast podbijać ocenę.

Lista rzeczy do sprawdzenia w OSM/geoportalu (deep-dive), zanim oferta awansuje na „dopasowane":
- **czynna linia kolejowa** — liczy się odległość od TORU, nie od stacji (stacja może być kilka km dalej,
  a hałas robi tor; orientacyjne minimum to ~1,5–2 km);
- **droga ekspresowa / krajowa / wojewódzka** o dużym ruchu, także **planowana** (S19, obwodnice);
- **cmentarz** — patrz niżej, ma skutek prawny;
- **ferma przemysłowa** (chlewnia, kurnik, obora), zabudowa zagrodowa z hodowlą, biogazownia;
- **teren przemysłowy, wyrobisko, żwirownia, tartak, składowisko, oczyszczalnia**;
- **farma wiatrowa**, linia wysokiego napięcia nad działką;
- **teren zalewowy** (doliny rzek), osuwiska.

### Cmentarz — twarde ograniczenie prawne
§ 3 rozporządzenia Ministra Gospodarki Komunalnej z 25.08.1959 (Dz.U. 1959 nr 52 poz. 315): odległość
cmentarza od zabudowań mieszkalnych **oraz od studni i źródeł wody pitnej** ma wynosić **min. 150 m**.
Może zostać zmniejszona do **50 m** tylko wtedy, gdy teren w pasie 50–150 m ma sieć wodociągową
i wszystkie budynki korzystające z wody są do niej podłączone.

Konsekwencja dla nas: przy planach **własnej studni** działka bliżej niż 150 m od cmentarza jest praktycznie
wykluczona — redukcja do 50 m wymaga rezygnacji ze studni na rzecz wodociągu. Cmentarz dalej niż 150 m
nie tworzy bariery prawnej, ale pozostaje minusem jakościowym (sąsiedztwo, ruch w święta).

## Region — trzy równorzędne kierunki
- **Gmina Rozprza i gmina Sulejów** (łódzkie, powiat piotrkowski) — główny kierunek.
  **UWAGA na korytarz hałasu**: przez gminę Rozprza biegną **linia kolejowa nr 1 (Warszawa–Katowice)
  i DK91**, a kilka km na zachód **A1** — to dokładnie ten układ dwóch źródeł hałasu naraz, którego
  unikamy. Oferty w tym korytarzu oceniaj SUROWO, niezależnie od ceny
  i areału; szukaj na wschód od niego. W gminie Sulejów dodatkowo sprawdzaj strefę ochronną Zalewu
  Sulejowskiego i Nadpilicki PK (ograniczenia zabudowy);
- **Dolny Śląsk: Wleń, Klecza** i okolice;
- **Okolice Ełku** (warmińsko-mazurskie) — kierunek rozważany wcześniej, nadal aktualny.
- **Beskid Niski / Pogórze Dynowskie** (podkarpackie, okolice Dukli) — najmocniejszy kierunek pod pasiekę:
  spadź z Beskidu Niskiego ma unijne ChNP, do tego lipa i akacja. Ziemia bywa po 2–4 zł/m², bardzo cicho,
  ciemne niebo, dużo porolnych gruntów w większych kawałkach. Minus: odległość i słabsza infrastruktura.
- **Podlasie: Bielsk Podlaski / Hajnówka** — zagłębie **gryki**, najciemniejsze niebo w kraju, brak przemysłu,
  ziemia 3–5 zł/m². Minus: ostrzejsza zima wydłuża zimowlę pszczół.
- **Góry Kaczawskie / powiat lwówecki** (okolice Świerzawy) — rozszerzenie sprawdzonego kręgu Wlenia
  na wschód.

**Krajobraz NIE musi być górzysty.** Góry są mile widziane, ale przestały być wymaganiem — jeśli oferta jest
w Sudetach i spełnia resztę (areał, pożytki, cisza), oceniaj ją normalnie, bez premii za sam fakt gór
i bez kary za teren płaski. Liczy się **spokój i przestrzeń do życia**, nie wysokość n.p.m.

## Powierzchnia i forma własności
- **Minimum 1 ha (10 000 m²)** — poniżej tylko wyjątkowo (np. działka przylegająca do większego terenu,
  rewelacyjne pożytki albo bardzo niska cena). Cel to powiększenie areału, więc drobnica mija się z celem.
- **Wymarzone 2–5 ha i więcej**, górnej granicy brak — **im więcej tym lepiej**.
- **Ziemia rolna jest w pełni w grze, wręcz preferowana** — uprawnienia rolnika są po stronie kupującego,
  więc ustawa o kształtowaniu ustroju rolnego nie stanowi bariery. To przewaga: grunty rolne są tańsze
  i mają mniejszą konkurencję niż działki budowlane.
- **Łąki, pastwiska, grunty orne, las, nieużytki** — wszystko akceptowalne.
- **Łączenie 2–3 sąsiednich działek** w jeden teren jest OK.
- **Preferowana jest SAMA ZIEMIA, bez zabudowań.** Płacę za areał i pożytki, nie za mury — budynek podnosi
  cenę, wnosi koszt remontu i ryzyko (stan techniczny, prawo budowlane), a nie jest tym, czego szukam.
- **Zabudowania nie dyskwalifikują**: siedlisko, gospodarstwo czy dom do remontu na dużym terenie są
  akceptowalne, jeśli ziemia się zgadza. Ale **nie są plusem** — nie podbijaj za nie oceny. Przy ofercie
  z zabudowaniami patrz, ile z ceny idzie na ziemię: jeśli budynek zjada budżet, który miał kupić areał,
  to minus, nie atut.
- Klasa gleby ma znaczenie drugorzędne (to nie jest zakup pod towarową produkcję roślinną), ale słaba klasa
  bywa plusem: tańsza i łatwiejsza do wyłączenia z produkcji.

## Cena za metr — osobne kryterium dla ziemi rolnej
Przy zakupie areału decyduje **cena jednostkowa, nie kwota na ogłoszeniu**. Dla **gruntu ROLNEGO**:
- **do ~4–5 zł/m² — cel**; tak wycenia się ziemię rolną kupowaną pod areał i tego szukamy;
- **5–10 zł/m² — akceptowalne tylko z uzasadnieniem**: rewelacyjne pożytki, las w cenie, duży zwarty
  kawałek, woda na działce. Sam ładny widok tego nie uzasadnia;
- **powyżej ~10 zł/m² za rolną — słaba wartość**: to już cena „działki pod coś", a nie ziemi pod areał.
  Obniżaj ocenę, nawet jeśli kwota mieści się w budżecie.

**To kryterium NIE dotyczy działek budowlanych, siedliskowych i ofert z zabudowaniami** — tam stawka za m²
z natury jest wielokrotnie wyższa i porównywanie jej z ceną ziemi rolnej nie ma sensu. Takie oferty oceniaj
całościowo (czy cena jest rozsądna na tle okolicy), a nie progiem 5 zł/m².

Gdy oferta miesza jedno z drugim (np. 3 ha rolnej + siedlisko), spróbuj rozdzielić: ile kosztuje sama ziemia,
a ile dopłata za zabudowania — i oceń, czy ta dopłata jest tego warta.

## Praktyczne — pod docelowe zamieszkanie
- **Dojazd drogą publiczną przejezdną zimą** (nie służebność przez cudze pole, nie polna ścieżka bez utrzymania).
- **Prąd** w działce lub realnie doprowadzalny; **woda** (studnia/wodociąg).
- **Internet** (światłowód / dobry zasięg) — istotny dla pracy zdalnej.
- **Sklep i szpital** w rozsądnym zasięgu samochodem — potrzebne do życia na co dzień, ale **nie ważniejsze
  niż cisza**. Bliskość stacji kolejowej jest wygodą, ale **nigdy kosztem hałasu torów**.

> Ogłoszenie zwykle nie poda tego wprost — jeśli brak danych, **nie zgaduj na korzyść**:
> oznacz „do weryfikacji" zamiast zawyżać score.

## Dyskwalifikujące (niska ocena / odrzucenie)
- **Blisko czynnej linii kolejowej, drogi ekspresowej/krajowej** lub innego stałego źródła hałasu.
- **Ferma przemysłowa** (chlewnia, kurnik, obora) w sąsiedztwie.
- **Ciężki przemysł, skażenie, składowisko, wyrobisko, biogazownia** w okolicy.
- **Brak dojazdu** drogą publiczną; teren **zalewowy** lub osuwiskowy.
- **Środek osiedla / gęstej zabudowy**, działka wciśnięta między sąsiadów.
- **ROD, udział we współwłasności, grunt bez uregulowanego stanu prawnego.**
- Teren bez jakiegokolwiek potencjału pożytkowego **i** bez przestrzeni (mały skrawek w polu kukurydzy).

## Mile widziane (podnoszą ocenę)
- Sprzedaż **od właściciela** (mniej prowizji).
- **Las lub zadrzewienia** na działce albo bezpośrednio przy niej.
- **Woda**: rzeka, potok, staw, oczko wodne, podmokła łąka.
- Sąsiedztwo **drobnych lub ekologicznych gospodarstw** zamiast wielkoobszarowej chemii.
- **Ciemne niebo**, brak łuny miejskiej.
- Widok i ekspozycja — przyjemne, ale **nie wymagane**.
- Rozsądna cena za m²/ha na tle okolicy; dobry stan prawny (KW, dostęp, brak współwłasności).

## Uwagi
- **Zmiana założeń (14.09.2026):** wcześniejsza wersja kryteriów celowała w **działkę pod dom całoroczny
  w Sudetach** (gmina Walim, Góry Sowie, powiat kłodzki), min. 3000 m², z naciskiem na widok i stok.
  Obecne kryteria są inne: **areał rolny + pasieka + cisza**, min. 1 ha, inne regiony.
  Poprzednia wersja leży w `properties/criteria.md.bak-20260914-153228`.
- **Domy i gospodarstwa**: przeszukiwane nadal (`include_homes: true`), ale **nie są preferowane** —
  patrz „Powierzchnia i forma własności". Szukamy ich po to, żeby nie przegapić dużego areału, który
  przypadkiem ma na sobie budynek. Scrapery obsługują je
  przez `--kind dom` — dla domów `area_m2` to powierzchnia **działki/terenu** (pow. budynku w
  `raw.house_area_m2`).
- Działki **wytypowane samodzielnie z geoportalu** (bez ogłoszenia) dodawane są przez
  `properties-list-manage` z `source_type: geoportal`.
- `price_max` = **500 tys.** — górny budżet na całość transakcji. Przy docelowej cenie ziemi rolnej
  (4–5 zł/m²) mieści się w nim kilkanaście hektarów. Oferty z zabudowaniami zwykle ten pułap przebijają
  i wypadną na pre-screenie — zgodnie z zasadą, że zabudowania nie są celem zakupu.
