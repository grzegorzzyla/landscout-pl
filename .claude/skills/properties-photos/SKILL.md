---
name: properties-photos
description: "Przegląda wzrokowo zdjęcia oferty i ustawia zdjęcie główne (reprezentatywne) oraz wykrywa zdjęcie mapki/planu (kataster/aerial/szkic geodezyjny). Zapisuje pola cover i map_photo w pliku .md. Uruchamiać w agencie general-purpose (czytanie zdjęć jest kontekstowo ciężkie), zwykle partią id."
when_to_use: "wybierz zdjęcie główne, ustaw cover oferty, znajdź zdjęcie mapki, analiza zdjęć działki, reprezentatywne zdjęcie, mapka z ogłoszenia, foto-analiza ofert"
argument-hint: "<ID listingu lub lista ID> "
allowed-tools: Bash, Read, Glob
model: sonnet
---

# properties-photos — zdjęcie główne + wykrycie mapki

Dla podanych ofert wybierasz **zdjęcie reprezentatywne** (cover) i — jeśli jest — **zdjęcie mapki/planu**
(map_photo), po czym zapisujesz je w `.md`. To czynność wzrokowa: metadane nie mówią, które zdjęcie jest
ładne ani które jest mapą — trzeba zobaczyć. Uruchamiaj z katalogu projektu, prefiks `PYTHONIOENCODING=utf-8`.

> **Rozdział ról:** tylko klasyfikujesz zdjęcia i zapisujesz `cover`/`map_photo` przez `manage_listing.py`.
> Nie oceniasz dopasowania oferty (to `properties-eval`/`properties-deep-dive`).

## Dla każdego `id`:
1. **Zbierz zdjęcia**: `Glob` po `properties/photos/<id>/*` (posortowane po nazwie 01,02,…). Jeśli pusto —
   pomiń z adnotacją „brak zdjęć". Ścieżka względna zapisywana w polach to `photos/<id>/<plik>`.
2. **Obejrzyj** (narzędziem `Read`) do ~12 zdjęć. Dla każdego ustal w myślach typ: krajobraz/widok,
   działka/teren, dom/budynek, wnętrze, mapka/plan, dokument, inne.
3. **Wybierz `cover`** — jedno, najbardziej reprezentatywne i „sprzedające" zgodnie z profilem poszukiwań:
   preferuj **widok/panoramę górską, ekspozycję terenu, działkę w otulinie** (to, co decyduje wg kryteriów);
   dla domu/siedliska — ładne ujęcie budynku w otoczeniu. **Unikaj** jako cover: mapek/planów, dokumentów,
   zrzutów, zdjęć rozmytych, ciemnych, z dużym znakiem wodnym, wnętrz (chyba że to dom i nie ma nic lepszego).
4. **Wykryj `map_photo`** — zdjęcie będące **mapą/planem**: zrzut z geoportalu/Google, mapa katastralna
   z obrysem działki, zdjęcie lotnicze z granicami, szkic geodezyjny/podziału. Wybierz najczytelniejsze.
   Jeśli żadne zdjęcie nie jest mapą — `map_photo` = brak (nie wymuszaj).
5. **Zapisz**:
   ```
   PYTHONIOENCODING=utf-8 python scripts/manage_listing.py set --id <id> --field cover --value "photos/<id>/<plik>"
   # tylko jeśli wykryto mapkę:
   PYTHONIOENCODING=utf-8 python scripts/manage_listing.py set --id <id> --field map_photo --value "photos/<id>/<plik>"
   ```

## Output
Zwróć zwięźle, po jednej linii na ofertę: `id — cover: <plik> · map_photo: <plik|—> (<liczba obejrzanych>)`.
Oferty bez zdjęć lub bez czytelnego cover wymień osobno.

## Zasady
- **Budżet**: ≤12 zdjęć na ofertę; przy partii wielu id trzymaj się limitu, by nie przepalić kontekstu.
  Po przekroczeniu — zwróć wynik częściowy z adnotacją.
- **Nie zgaduj**: jeśli nie widać dobrego cover, wybierz pierwsze sensowne zdjęcie terenu i odnotuj wątpliwość;
  jeśli nie ma mapy — nie ustawiaj `map_photo`.
- **Ścieżki względne** dokładnie jak w polu `photos[]` (`photos/<id>/<plik>`), bez wiodącego `/`.
- **Zapis tylko przez `manage_listing.py`**.
