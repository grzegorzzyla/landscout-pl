# cdp — uruchom Claude Code CLI (NIE Claude Desktop; ten drugi bywa na PATH jako `claude` i `-p` zwraca puste).
# Wersja projektowa (self-contained, bez ścieżek per-user) — używana przez stronę i skille.
#
# Rozwiązanie ścieżki do claude.exe (w tej kolejności):
#   1) zmienna środowiskowa CLAUDE_EXE (jeśli wskazuje istniejący plik),
#   2) najnowsza wersja w %APPDATA%\Claude\claude-code\<wersja>\claude.exe,
#   3) `claude` z PATH (np. instalacja globalna).
#
# Tryby:
#   cdp --which                 # wypisz ścieżkę do claude.exe i wyjdź (tego używa backend strony)
#   cdp -p "<prompt>" [...]      # headless: passthrough argumentów + --dangerously-skip-permissions
#   cdp                          # interaktywny --remote-control, nazwa sesji = bieżąca data/godzina
#   cdp "<nazwa sesji>"          # interaktywny --remote-control z podaną nazwą
param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$Rest
)

function Resolve-ClaudeExe {
  if ($env:CLAUDE_EXE -and (Test-Path -LiteralPath $env:CLAUDE_EXE)) { return $env:CLAUDE_EXE }
  $base = Join-Path $env:APPDATA 'Claude\claude-code'
  if (Test-Path -LiteralPath $base) {
    $ver = Get-ChildItem -Directory -LiteralPath $base |
      Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'claude.exe') } |
      Sort-Object { try { [version]$_.Name } catch { [version]'0.0' } } -Descending |
      Select-Object -First 1
    if ($ver) { return (Join-Path $ver.FullName 'claude.exe') }
  }
  $cmd = Get-Command claude -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  throw "Nie znaleziono Claude Code (claude.exe). Ustaw zmienną CLAUDE_EXE."
}

$exe = Resolve-ClaudeExe
$Rest = @($Rest)

if ($Rest.Count -ge 1 -and $Rest[0] -eq '--which') { Write-Output $exe; exit 0 }

# Headless: gdy w argumentach jest -p/--print, przepuść je i dołóż pominięcie pytań o uprawnienia.
if (($Rest -contains '-p') -or ($Rest -contains '--print')) {
  & $exe @Rest --dangerously-skip-permissions
  exit $LASTEXITCODE
}

# Interaktywny remote-control.
$session = if ($Rest.Count -ge 1) { $Rest[0] } else { Get-Date -Format 'yyyy-MM-dd HH:mm:ss' }
& $exe --dangerously-skip-permissions --remote-control "$session"
exit $LASTEXITCODE
