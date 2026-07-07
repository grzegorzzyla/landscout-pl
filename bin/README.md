# bin/cdp — launcher Claude Code CLI

`cdp` uruchamia **Claude Code CLI** (nie Claude Desktop — ten bywa na PATH jako `claude` i w trybie `-p`
zwraca puste wyjście). Używają go backend strony (`site/src/server/runner.ts`) oraz ręczne/headless
wywołania skili. Trzymany w repo, żeby projekt był self-contained (open-source) — bez ścieżek per-user.

## Warianty
- `bin/cdp.ps1` — rdzeń (Windows PowerShell).
- `bin/cdp.cmd` — wrapper dla cmd/PATH (woła `cdp.ps1`).
- `bin/cdp` — wariant POSIX (macOS/Linux): `bash bin/cdp …` lub po `chmod +x`.

## Rozwiązanie ścieżki do `claude.exe` / `claude`
1. `CLAUDE_EXE` (jeśli wskazuje istniejący plik) — nadrzędne, do wskazania ręcznego.
2. Windows: najnowsza wersja w `%APPDATA%\Claude\claude-code\<wersja>\claude.exe`.
3. `claude` z PATH (instalacja globalna; głównie macOS/Linux).

## Użycie
```
cdp --which                 # wypisz ścieżkę do binarki i wyjdź (backend strony bierze stąd ścieżkę)
cdp -p "<prompt>" [...]      # headless: przepuszcza argumenty + dokłada --dangerously-skip-permissions
cdp                          # interaktywny --remote-control (nazwa sesji = data/godzina)
cdp "<nazwa sesji>"          # interaktywny --remote-control z podaną nazwą
```

Uwaga (headless): przy wywołaniu programistycznym odcinaj stdin (`< NUL` / `< /dev/null`), inaczej Claude
Code czeka ~3 s na wejście. Backend strony spawnuje binarkę bezpośrednio (argv) — `cdp --which` służy mu
tylko do ustalenia ścieżki, dzięki czemu „jak uruchomić Claude Code" ma jedno źródło prawdy.
