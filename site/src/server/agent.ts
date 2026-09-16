// Panel agentury: kontrole stanu wykonywane na żądanie ze strony.
//
// Każda kontrola uruchamia REALNY proces (wersja CLI, import bibliotek, start Chromium), a nie
// sprawdza obecności pliku — bo dziś kilka razy okazało się, że plik jest, a i tak nie działa
// (prawa katalogu, inny interpreter, katalog konfiguracji gdzie indziej).
// Obsługa tokenu siedzi w ./claude-auth, wspólnie z runnerem i czatem.
import { execFileSync, execSync } from 'node:child_process';
import { existsSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { PROJECT_DIR, pythonExe, resolveClaudeExeCached } from './runner';
import { claudeEnv, authSource } from './claude-auth';

export { authSource };

export type Check = { name: string; ok: boolean; detail: string };

function check(name: string, fn: () => string): Check {
  try {
    return { name, ok: true, detail: fn() };
  } catch (e: any) {
    return { name, ok: false, detail: String(e?.message ?? e).split('\n')[0].slice(0, 200) };
  }
}

export function collectStatus(): { checks: Check[]; authSource: string } {
  const checks: Check[] = [];

  // Kiedy zbudowano obraz. Bierzemy datę pliku wyjściowego builda, bo `.git` jest wyłączony
  // z kontekstu budowania, a `RUN date > plik` w Dockerfile byłby CACHE'OWANY i zamrażał
  // jedną datę na zawsze. Odpowiada na pytanie "czy patrzę na nowy kod?", które dziś wracało
  // kilkukrotnie przy każdej przebudowie.
  checks.push(check('Wersja obrazu', () => {
    const entry = join(PROJECT_DIR, 'site', 'dist', 'server', 'entry.mjs');
    if (!existsSync(entry)) return 'nie znaleziono artefaktu builda';
    return `zbudowany ${statSync(entry).mtime.toLocaleString('pl-PL')}`;
  }));

  checks.push(check('Claude Code', () => {
    const exe = resolveClaudeExeCached();
    const v = execFileSync(exe, ['--version'], { encoding: 'utf-8', timeout: 20000 }).trim();
    return `${v} (${exe})`;
  }));

  checks.push(check('Autoryzacja Claude', () => {
    const exe = resolveClaudeExeCached();
    const out = execFileSync(exe, ['auth', 'status'], {
      encoding: 'utf-8', timeout: 30000, env: claudeEnv(),
    }).trim();
    // wyjście bywa wielolinijkowe — bierzemy pierwsze niepuste linie
    return out.split('\n').filter(Boolean).slice(0, 3).join(' · ') || 'brak odpowiedzi';
  }));

  checks.push(check('Python + zależności', () => {
    const out = execFileSync(pythonExe(), ['-c',
      'import yaml, httpx, lxml; print("yaml, httpx, lxml OK")'],
      { encoding: 'utf-8', timeout: 20000 }).trim();
    return out;
  }));

  checks.push(check('Chromium (Playwright)', () => {
    const out = execFileSync(pythonExe(), ['-c',
      'from playwright.sync_api import sync_playwright\n' +
      'with sync_playwright() as p:\n' +
      '    b = p.chromium.launch(headless=True); v = b.version; b.close()\n' +
      'print("chromium " + v)'],
      { encoding: 'utf-8', timeout: 60000 }).trim();
    return out;
  }));

  checks.push(check('Sesja Facebook', () => {
    const profile = join(PROJECT_DIR, 'scripts', '.fb_profile');
    if (!existsSync(profile)) return 'brak profilu — nie zalogowano';
    const out = execSync(
      `find ${JSON.stringify(profile)} -name Cookies -maxdepth 3 2>/dev/null | head -1`,
      { encoding: 'utf-8', timeout: 15000 }).trim();
    if (!out) return 'profil bez ciasteczek — nie zalogowano';
    return 'profil istnieje (ważność sprawdza dopiero skan)';
  }));

  checks.push(check('Baza ofert', () => {
    const dir = join(PROJECT_DIR, 'properties', 'listings');
    if (!existsSync(dir)) return 'brak katalogu properties/listings';
    const files = readdirSync(dir).filter((f) => f.endsWith('.md'));
    const photos = join(PROJECT_DIR, 'properties', 'photos');
    const photoDirs = existsSync(photos) ? readdirSync(photos).length : 0;
    return `${files.length} ofert, ${photoDirs} katalogów ze zdjęciami`;
  }));

  checks.push(check('Kryteria', () => {
    const f = join(PROJECT_DIR, 'properties', 'criteria.md');
    if (!existsSync(f)) return 'BRAK criteria.md — wyszukiwanie i ocena nie zadziałają';
    const st = statSync(f);
    return `${(st.size / 1024).toFixed(1)} kB, zmienione ${st.mtime.toLocaleString('pl-PL')}`;
  }));

  return { checks, authSource: authSource() };
}
