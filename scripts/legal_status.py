"""
legal_status.py — sygnały o stanie prawnym wyłuskane z TREŚCI ogłoszenia.

Po co to jest: hipoteki, służebności i egzekucje widać wyłącznie w księdze wieczystej, a otwartej
bazy KW nie ma i nie będzie — EKW (ekw.ms.gov.pl) wyszukuje WYŁĄCZNIE po pełnym 13-znakowym numerze
księgi, nie po działce ani adresie, i to jest świadoma ochrona danych osobowych, nie niedoróbka.
Mapowania działka → numer KW publicznie nie ma; numer dostaje się od sprzedającego, z aktu
notarialnego albo z wypisu z EGiB w starostwie.

Czego ten moduł NIE robi: nie odpytuje EKW. Przeglądarka EKW stoi za Incapsulą i działa na POST,
więc deep-link do konkretnej księgi jest niemożliwy — zwracamy adres wyszukiwarki, a numer idzie
do skopiowania. Automatyzowanie jej byłoby i tak niezgodne z regulaminem i padłoby przy pierwszej
zmianie strony.

Co robi: czyta tytuł i opis, wyciąga numer KW (z WALIDACJĄ cyfry kontrolnej — bez niej regex łapie
przypadkowe ciągi typu numerów katastralnych) i oznacza wzmianki o stanie prawnym.

!!! Flagi to CYTATY ZE SPRZEDAJĄCEGO, nie fakty. „Bez obciążeń" w ogłoszeniu znaczy tyle, że tak
napisano — potwierdza to wyłącznie dział III i IV księgi. Nazewnictwo flag celowo o tym przypomina.
"""
from __future__ import annotations

import re

# Wyszukiwarka EKW — bez numeru nie da się nic otworzyć, więc link prowadzi do formularza.
EKW_URL = "https://przegladarka-ekw.ms.gov.pl/eukw_prz/KsiegiWieczyste/wyszukiwanieKsiegiWieczystej"

# Wartości znaków i wagi do cyfry kontrolnej numeru KW (12 znaków: 4 kod wydziału + 8 numeru).
_VAL = {**{str(i): i for i in range(10)},
        "X": 10, "A": 11, "B": 12, "C": 13, "D": 14, "E": 15, "F": 16, "G": 17, "H": 18,
        "I": 19, "J": 20, "K": 21, "L": 22, "M": 23, "N": 24, "O": 25, "P": 26, "R": 27,
        "S": 28, "T": 29, "U": 30, "W": 31, "Y": 32, "Z": 33}
_WEIGHTS = [1, 3, 7]

# kod wydziału: 2 litery + cyfra + litera (np. SW1K, BI1P, PT1P)
_KW_RE = re.compile(r"\b([A-Z]{2}\d[A-Z])\s*[/\-]\s*(\d{8})\s*[/\-]\s*(\d)\b")


def check_digit(court: str, number: str):
    """Cyfra kontrolna numeru KW. Zwraca int albo None, gdy znaki spoza alfabetu."""
    s = (court + number).upper()
    if len(s) != 12 or any(c not in _VAL for c in s):
        return None
    return sum(_VAL[c] * _WEIGHTS[i % 3] for i, c in enumerate(s)) % 10


def find_kw(text: str):
    """Pierwszy numer KW o POPRAWNEJ cyfrze kontrolnej. Bez walidacji regex łapie śmieci."""
    for court, number, ctrl in _KW_RE.findall(text or ""):
        if check_digit(court, number) == int(ctrl):
            return f"{court}/{number}/{ctrl}"
    return None


# Formuły prawne z obwieszczeń komorniczych — stały szablon, który pojawia się w KAŻDYM
# obwieszczeniu niezależnie od nieruchomości („Użytkowanie, służebności i prawa dożywotnika,
# jeżeli nie są ujawnione…"). Bez wycięcia każda licytacja dostawała flagę służebności.
_BOILERPLATE = [
    r"u[żz]ytkowanie,?\s*s[łl]u[żz]ebno[śs]ci\s+i\s+prawa\s+do[żz]ywotnika.{0,200}",
    r"je[żz]eli\s+nie\s+s[ąa]\s+ujawnione\s+w\s+ksi[ęe]dze\s+wieczystej.{0,200}",
]

# Zaprzeczenie tuż przed wzmianką odwraca jej sens: „bez służebności" to deklaracja czystości,
# a nie obciążenie. Bez tego oferta z „żadnych zadłużeń ani służebności" dostawała flagę
# dokładnie odwrotną do tego, co napisał sprzedający.
_NEGATION = r"(?:bez|brak|[żz]adn\w*|ani|woln\w*\s+od|nieobci[ąa][żz]\w*|nie\s+jest\s+obci[ąa][żz])"

# Wzmianki o stanie prawnym: (nazwa, wzorzec, kontekst wykluczający albo None).
_FLAG_PATTERNS = [
    # Licytacja komornicza to jedyny TWARDY sygnał: obwieszczenie jest urzędowe, a nieruchomość
    # w egzekucji. Reszta to deklaracje sprzedającego, które weryfikuje dopiero księga.
    ("licytacja-komornicza",
     r"komornik\w*\s+s[ąa]dow|obwieszczenie\s+o\s+(?:sprzeda|licytacj)|"
     r"licytacj\w*\s+(?:elektroniczn|nieruchomo)|w\s+drodze\s+licytacji", None),
    # „zabezpieczenie — tylko hipoteka" to OFERTA RATALNA sprzedającego, nie obciążenie działki.
    ("wzmianka-hipoteka", r"hipotek\w*",
     r"zabezpieczen|zdolno[śs]ci\s+kredytow|kredyt|rat[ay]|finansowan|po[żz]yczk|rozk[łl]ad"),
    ("sluzebnosc", r"s[łl]u[żz]ebno[śs]\w*", None),
    ("deklaracja-bez-obciazen",
     r"bez\s+(?:[żz]adnych\s+)?obci[ąa][żz]e[ńn]|brak\s+(?:jakichkolwiek\s+)?obci[ąa][żz]e[ńn]|"
     r"czyst\w*\s+ksi[ęe]g\w*|stan\s+prawny\s+czysty|wolna?\s+od\s+obci[ąa][żz]e[ńn]", None),
]


def _strip_boilerplate(low: str) -> str:
    for pat in _BOILERPLATE:
        low = re.sub(pat, " ", low, flags=re.I | re.S)
    return low


def scan(text: str) -> dict:
    """Sygnały ze wskazanego tekstu (tytuł + opis). Pusty wynik = brak wzmianek, NIE „czysto"."""
    t = text or ""
    low = _strip_boilerplate(t.lower())
    flags: list[str] = []
    negated_any = False

    for name, pat, exclude in _FLAG_PATTERNS:
        present = False
        for m in re.finditer(pat, low, re.I):
            before = low[max(0, m.start() - 60):m.start()]
            if exclude and re.search(exclude, low[max(0, m.start() - 90):m.end() + 60], re.I):
                continue                      # inny kontekst niż obciążenie nieruchomości
            if re.search(_NEGATION + r"[^.;]{0,40}$", before, re.I):
                negated_any = True            # „bez służebności" — deklaracja, nie obciążenie
                continue
            present = True
            break
        if present:
            flags.append(name)

    if negated_any and "deklaracja-bez-obciazen" not in flags:
        flags.append("deklaracja-bez-obciazen")

    out: dict = {}
    kw = find_kw(t)
    if kw:
        out["kw_number"] = kw
    if flags:
        out["flags"] = flags
    return out


def from_record(fm: dict) -> dict:
    """Sygnały z rekordu oferty (tytuł + opis)."""
    return scan(" ".join(str(fm.get(k) or "") for k in ("title", "description")))
