#!/usr/bin/env bash
# Entrypoint kontenera LandScout. Robi rzeczy, których nie da się załatwić w Dockerfile,
# bo zależą od wolumenów montowanych dopiero przy starcie.
#
# Proces uruchamiamy jako PUID:PGID NUMERYCZNIE (gosu 1000:10), bez tworzenia i przestawiania
# użytkownika. Wcześniejsza wersja robiła useradd + usermod -u: użytkownik dostawał przy budowaniu
# UID 1001 (1000 zajmuje `node` z obrazu bazowego), pliki chownowane na 1001, a po starcie proces
# miał już 1000 — i tracił dostęp do własnych plików. Numery z compose omijają ten problem w całości.
set -euo pipefail

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
DATA_DIR="${ASSISTANT_DIR:-/app}/properties"
ENTRY=/app/site/dist/server/entry.mjs
RUN_AS="${PUID}:${PGID}"
HOME_DIR="${HOME:-/home/landscout}"

# --- katalog danych ----------------------------------------------------------------
# Bez `chown -R` na properties/: przy setkach MB zdjęć wydłużałoby każdy start, a właścicielem
# zarządza NAS. Tworzymy tylko brakującą strukturę.
mkdir -p "$DATA_DIR/listings/deleted" "$DATA_DIR/photos" 2>/dev/null || true
# Katalogi tworzone tu powstają jako ROOT (entrypoint działa przed gosu), więc proces docelowy
# nie mógłby do nich pisać. Chown TYLKO na te kilka katalogów — bez -R, żeby nie przemielać zdjęć.
chown "$RUN_AS" "$DATA_DIR" "$DATA_DIR/listings" "$DATA_DIR/listings/deleted" \
      "$DATA_DIR/photos" 2>/dev/null || true

if [ ! -f "$DATA_DIR/criteria.md" ] && [ -f /app/properties.default/criteria.md ]; then
  install -m 0644 /app/properties.default/criteria.md "$DATA_DIR/criteria.md" 2>/dev/null || true
fi

# Kryteria muszą być czytelne i zapisywalne dla procesu — czyta je pre-screen i ocena, a strona
# docelowo pozwoli je edytować. Sprawdzamy przy KAŻDYM starcie, nie tylko przy tworzeniu: plik
# mógł zostać na wolumenie po wcześniejszym uruchomieniu z innymi prawami (wolumen przeżywa
# przebudowy obrazu, więc raz źle nadane prawa zostają na zawsze).
if [ -f "$DATA_DIR/criteria.md" ] && ! gosu "$RUN_AS" test -w "$DATA_DIR/criteria.md" 2>/dev/null; then
  echo "[landscout] naprawiam prawa: criteria.md (był niedostępny dla ${RUN_AS})"
  chown "$RUN_AS" "$DATA_DIR/criteria.md" 2>/dev/null || true
  chmod 0644 "$DATA_DIR/criteria.md" 2>/dev/null || true
fi

# --- stan kolejki -------------------------------------------------------------------
# Katalog powstaje jako root (entrypoint działa przed gosu), więc od razu oddajemy go procesowi.
mkdir -p /app/state/jobs /app/state/logs 2>/dev/null || true
chown -R "$RUN_AS" /app/state 2>/dev/null || true

# --- HOME procesu -------------------------------------------------------------------
# Claude Code trzyma tu poświadczenia, sesje i historię rozmów (.claude to osobny wolumen).
mkdir -p "$HOME_DIR/.claude" 2>/dev/null || true
chown "$RUN_AS" "$HOME_DIR" "$HOME_DIR/.claude" 2>/dev/null || true

# --- zaufanie do katalogu projektu -------------------------------------------------
# Bez tego Claude Code ignoruje permissions.allow z .claude/settings.json ("this workspace has
# not been trusted") i wypisuje ostrzeżenie przy każdym uruchomieniu. Interaktywnego dialogu
# w kontenerze nie ma kto kliknąć, więc ustawiamy flagę wprost — scalając z istniejącym plikiem,
# żeby nie skasować historii ani innych ustawień.
CFG_DIR="${CLAUDE_CONFIG_DIR:-$HOME_DIR/.claude}"
CFG_JSON="$CFG_DIR/.claude.json"
mkdir -p "$CFG_DIR" 2>/dev/null || true
python3 - "$CFG_JSON" "${ASSISTANT_DIR:-/app}" <<'PYEOF' 2>/dev/null || true
import json, os, sys
path, project = sys.argv[1], sys.argv[2]
data = {}
if os.path.exists(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh) or {}
    except Exception:
        data = {}
projects = data.setdefault("projects", {})
entry = projects.setdefault(project, {})
if not entry.get("hasTrustDialogAccepted"):
    entry["hasTrustDialogAccepted"] = True
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
PYEOF
chown -R "$RUN_AS" "$CFG_DIR" 2>/dev/null || true

# --- zdjęcia ------------------------------------------------------------------------
# Strona serwuje statyki z dist/client, a zdjęcia leżą na wolumenie. Dowiązanie musi powstać
# PO zbudowaniu obrazu, bo w czasie budowania wolumenu jeszcze nie ma.
CLIENT_DIR=/app/site/dist/client
if [ -d "$CLIENT_DIR" ]; then
  rm -rf "$CLIENT_DIR/photos" 2>/dev/null || true
  ln -s "$DATA_DIR/photos" "$CLIENT_DIR/photos" 2>/dev/null || true
fi

# --- diagnostyka --------------------------------------------------------------------
echo "[landscout] ASSISTANT_DIR=${ASSISTANT_DIR:-/app}  proces jako ${RUN_AS}"
echo "[landscout] ofert w bazie: $(ls -1 "$DATA_DIR/listings"/*.md 2>/dev/null | wc -l | tr -d ' ')"

if command -v claude >/dev/null 2>&1; then
  if [ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
    echo "[landscout] Claude Code: token z CLAUDE_CODE_OAUTH_TOKEN"
  elif [ -f "$HOME_DIR/.claude/.credentials.json" ]; then
    echo "[landscout] Claude Code: poświadczenia z wolumenu claude-home"
  else
    echo "[landscout] UWAGA: brak autoryzacji Claude Code. Na swoim komputerze uruchom"
    echo "[landscout]        'claude setup-token' i wstaw wynik do CLAUDE_CODE_OAUTH_TOKEN,"
    echo "[landscout]        albo zaloguj sie w konsoli kontenera: claude auth login"
  fi
else
  echo "[landscout] UWAGA: nie znaleziono Claude Code — ingest/deep-dive/czat nie zadziałają"
fi

# Dostępność pliku sprawdzamy OCZAMI PROCESU DOCELOWEGO, nie roota — to jest ta różnica, przez
# którą poprzednia wersja przechodziła kontrolę, a `node` i tak zgłaszał "Cannot find module":
# root widział plik, użytkownik docelowy już nie.
if ! gosu "$RUN_AS" test -r "$ENTRY" 2>/dev/null; then
  echo "[landscout] BŁĄD: uzytkownik ${RUN_AS} nie moze odczytac $ENTRY"
  echo "[landscout] --- plik widziany przez roota ---"
  ls -la "$ENTRY" 2>&1 | head -3
  echo "[landscout] --- /app/site ---";        ls -la /app/site 2>&1 | head -15
  echo "[landscout] --- /app/site/dist ---";   ls -la /app/site/dist 2>&1 | head -15
  echo "[landscout] --- prawa wzdluz sciezki ---"; namei -l "$ENTRY" 2>&1 | head -12
  exit 1
fi

# LANDSCOUT_DEBUG=1 → wypisz stan przed startem. Przydatne, gdy kontener wpada w petle restartow
# i nie da sie do niego podlaczyc konsola.
if [ "${LANDSCOUT_DEBUG:-}" = "1" ]; then
  echo "[landscout][debug] --- /app/site/dist/server ---"; ls -la /app/site/dist/server 2>&1 | head -12
  echo "[landscout][debug] --- /app/properties ---";       ls -la "$DATA_DIR" 2>&1 | head -12
  echo "[landscout][debug] --- node ---";                  gosu "$RUN_AS" node --version 2>&1
  echo "[landscout][debug] --- python ---";                gosu "$RUN_AS" python3 -c "import yaml,httpx;print('yaml+httpx OK')" 2>&1
fi

exec gosu "$RUN_AS" "$@"
