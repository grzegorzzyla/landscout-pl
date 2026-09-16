// Autoryzacja Claude Code — wydzielona, bo korzystają z niej i runner (uruchamianie zadań),
// i panel agentury. Osobny moduł zapobiega cyklicznemu importowi między nimi.
//
// Token ze zmiennej CLAUDE_CODE_OAUTH_TOKEN wymaga redeployu stacku przy każdej wymianie.
// Dlatego dopuszczamy też token w PLIKU na wolumenie — wtedy rotacja to wklejenie nowego
// w przeglądarce. Plik ma pierwszeństwo: skoro ktoś go wgrał, zrobił to właśnie po to,
// żeby zastąpić wartość ze środowiska.
import { existsSync, readFileSync, writeFileSync, chmodSync } from 'node:fs';
import { join } from 'node:path';

export const CLAUDE_CONFIG_DIR =
  process.env.CLAUDE_CONFIG_DIR || join(process.env.HOME || '/home/landscout', '.claude');
const TOKEN_FILE = join(CLAUDE_CONFIG_DIR, 'oauth-token');

export function storedToken(): string | null {
  try {
    if (!existsSync(TOKEN_FILE)) return null;
    return readFileSync(TOKEN_FILE, 'utf-8').trim() || null;
  } catch {
    return null;
  }
}

export function saveToken(token: string): void {
  writeFileSync(TOKEN_FILE, token.trim() + '\n', { encoding: 'utf-8', mode: 0o600 });
  try { chmodSync(TOKEN_FILE, 0o600); } catch { /* np. na SMB chmod bywa bez efektu */ }
}

export function clearToken(): void {
  try {
    if (existsSync(TOKEN_FILE)) writeFileSync(TOKEN_FILE, '', { encoding: 'utf-8', mode: 0o600 });
  } catch { /* ignorujemy */ }
}

/** Środowisko dla procesów Claude Code — z tokenem z pliku, gdy istnieje. */
export function claudeEnv(): NodeJS.ProcessEnv {
  const t = storedToken();
  return t ? { ...process.env, CLAUDE_CODE_OAUTH_TOKEN: t } : process.env;
}

/** Skąd pochodzi autoryzacja — użytkownik ma widzieć, co realnie działa. */
export function authSource(): string {
  if (storedToken()) return 'token z panelu (plik na wolumenie)';
  if (process.env.CLAUDE_CODE_OAUTH_TOKEN) return 'token ze zmiennej środowiskowej';
  if (existsSync(join(CLAUDE_CONFIG_DIR, '.credentials.json'))) return 'logowanie interaktywne';
  return 'brak';
}
