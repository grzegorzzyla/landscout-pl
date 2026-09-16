#!/usr/bin/env bash
# Entrypoint kontenera LandScout. Robi trzy rzeczy, których nie da się załatwić w Dockerfile,
# bo zależą od zamontowanych wolumenów (istniejących dopiero przy starcie).
set -euo pipefail

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
DATA_DIR="${ASSISTANT_DIR:-/app}/properties"

# 1. Dopasowanie użytkownika do właściciela katalogu na NAS-ie. Bez tego pliki tworzone przez
#    kontener mają obcego właściciela i nie da się ich ruszyć z poziomu systemu plików NAS-a.
if [ "$(id -u landscout)" != "$PUID" ] || [ "$(id -g landscout)" != "$PGID" ]; then
  groupmod -o -g "$PGID" landscout 2>/dev/null || true
  usermod  -o -u "$PUID" -g "$PGID" landscout 2>/dev/null || true
  chown -R "$PUID:$PGID" /home/landscout 2>/dev/null || true
fi

# 2. Struktura katalogu danych. Celowo NIE robimy chown -R na properties/ — przy kilkuset
#    megabajtach zdjęć to wydłużałoby każdy start, a właścicielem zarządza NAS.
mkdir -p "$DATA_DIR/listings/deleted" "$DATA_DIR/photos" 2>/dev/null || true

if [ ! -f "$DATA_DIR/criteria.md" ] && [ -f /app/properties.default/criteria.md ]; then
  cp /app/properties.default/criteria.md "$DATA_DIR/criteria.md" || true
fi

# 3. Zdjęcia: strona serwuje statyki z dist/client, a katalog ze zdjęciami jest na wolumenie.
#    Dowiązanie musi powstać PO zbudowaniu obrazu, bo w czasie budowania wolumenu jeszcze nie ma.
#    (To ten sam mechanizm, co junction/symlink site/public/photos w instalacji lokalnej.)
CLIENT_DIR=/app/site/dist/client
if [ -d "$CLIENT_DIR" ]; then
  rm -rf "$CLIENT_DIR/photos"
  ln -s "$DATA_DIR/photos" "$CLIENT_DIR/photos"
fi

# Diagnostyka na start — najczęstsze przyczyny „nie działa" widać od razu w logu kontenera.
echo "[landscout] ASSISTANT_DIR=${ASSISTANT_DIR:-/app}  UID=$PUID GID=$PGID"
echo "[landscout] ofert w bazie: $(ls -1 "$DATA_DIR/listings"/*.md 2>/dev/null | wc -l | tr -d ' ')"
if command -v claude >/dev/null 2>&1; then
  echo "[landscout] Claude Code: $(command -v claude)"
  if [ ! -f /home/landscout/.claude/.credentials.json ]; then
    echo "[landscout] UWAGA: brak logowania Claude Code — otwórz konsolę kontenera i uruchom: claude"
  fi
else
  echo "[landscout] UWAGA: nie znaleziono Claude Code — ingest/deep-dive/czat nie zadziałają"
fi

exec gosu landscout "$@"
