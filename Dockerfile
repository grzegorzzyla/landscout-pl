# LandScout PL — jeden obraz: strona (Astro SSR) + agentura (Claude Code, scrapery, Playwright).
#
# Świadomie NIE dzielimy na osobne obrazy „web" i „agent": przy instalacji jednoosobowej
# jeden kontener to jeden log, jeden restart i jedna konfiguracja. Podział ma sens dopiero
# wtedy, gdy strona i agentura mają żyć na różnych maszynach.
#
# Dane (listings, photos, criteria.md) NIE są w obrazie — montujesz je z NAS-a pod /app/properties.
# Poświadczenia Claude Code i historia czatu żyją w /home/landscout/.claude (osobny wolumen),
# inaczej każde odtworzenie kontenera kasowałoby logowanie.
FROM node:22-bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    # katalog projektu czytany przez site/src/server/runner.ts (PROJECT_DIR)
    ASSISTANT_DIR=/app \
    # przeglądarki Playwrighta poza $HOME roota — inaczej użytkownik nie-root ich nie znajdzie
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright \
    VIRTUAL_ENV=/opt/venv \
    HOME=/home/landscout \
    # Claude Code ustala katalog konfiguracji z wpisu w passwd (dla UID 1000 to `node` z obrazu
    # bazowego), a NIE ze zmiennej HOME — sesje lądowałyby w /home/node/.claude, czyli poza
    # wolumenem, i ginęły przy każdym odtworzeniu kontenera. Wskazujemy katalog wprost.
    CLAUDE_CONFIG_DIR=/home/landscout/.claude

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-venv ca-certificates git gosu tini tzdata \
    && rm -rf /var/lib/apt/lists/*

# Python w venv: Debian bookworm blokuje instalację do systemowego Pythona (PEP 668),
# a venv jest czystszy niż --break-system-packages.
RUN python3 -m venv "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

WORKDIR /app

# Zależności Pythona osobną warstwą — rzadko się zmieniają, więc cache trzyma się długo.
COPY scripts/requirements.txt scripts/requirements.txt
RUN pip install --no-cache-dir -r scripts/requirements.txt

# Chromium potrzebny do: fallbacku Otodom (gdy zwróci 403) i skanera grup Facebooka.
RUN playwright install --with-deps chromium

# Claude Code — agentura (skille, ocena, deep-dive, docelowo czat).
RUN npm install -g @anthropic-ai/claude-code

# Zależności strony osobną warstwą, przed skopiowaniem kodu (cache).
COPY site/package.json site/package-lock.json site/
RUN cd site && npm ci

COPY . .

# criteria.md z repo służy jako WZORZEC. Katalog /app/properties jest przykrywany wolumenem
# z NAS-a, więc plik z obrazu i tak by zniknął — entrypoint kopiuje go stamtąd przy pierwszym
# starcie, gdy na wolumenie jeszcze nic nie ma.
RUN mkdir -p /app/properties.default \
    && if [ -f /app/properties/criteria.md ]; then \
         cp /app/properties/criteria.md /app/properties.default/criteria.md; \
       fi

RUN cd site && npm run build

# Twardy warunek: brak artefaktu ma wywalić BUDOWANIE, a nie wyprodukować obraz, który dopiero
# przy starcie krzyczy "Cannot find module". Gdy build Astro cicho nie wyprodukuje entry.mjs,
# chcemy zobaczyć to tutaj, razem z zawartością katalogu.
RUN test -f /app/site/dist/server/entry.mjs || { \
      echo "BŁĄD: build Astro nie wyprodukował site/dist/server/entry.mjs"; \
      echo "--- /app/site ---"; ls -la /app/site; \
      echo "--- /app/site/dist ---"; ls -laR /app/site/dist 2>/dev/null | head -40; \
      exit 1; }

# Kod aplikacji ma być czytelny dla DOWOLNEGO UID-u, bo proces uruchamiamy jako PUID:PGID
# podane w compose (numerycznie, przez gosu). Świadomie NIE robimy `chown` na katalogu z kodem:
# ustawiałby właściciela na UID przydzielony przy budowaniu (1001, bo 1000 zajmuje użytkownik
# `node` z obrazu bazowego), a po starcie proces ma już inny UID — pliki zostawałyby u
# osieroconego właściciela. Same prawa odczytu wystarczą i nie zależą od numerów.
# `COPY . .` przenosi prawa Z KONTEKSTU BUDOWANIA. Portainer klonuje repozytorium z
# restrykcyjnym umaskiem, więc katalogi trafiają do obrazu jako 0700 — a proces działa jako
# PUID:PGID, nie root, i nie przejdzie nawet przez /app/site do gotowej strony (objawia się
# jako "Cannot find module", choć plik istnieje i sam w sobie jest czytelny).
# Dlatego nadajemy prawa odczytu na CAŁYM drzewie aplikacji, nie na wybranych podkatalogach.
RUN mkdir -p /home/landscout /app/properties \
    && chmod -R a+rX /app \
    && chmod 0777 /home/landscout

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh /app/bin/cdp || true

EXPOSE 4321
ENV HOST=0.0.0.0 PORT=4321

# tini jako PID 1 — Claude Code i Chromium potrafią zostawiać procesy potomne.
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]
CMD ["node", "/app/site/dist/server/entry.mjs"]
