// Odczyt i zapis properties/criteria.md z walidacją i historią.
//
// Ten plik napędza pre-screen (area_min, price_max, locations) i całą ocenę jakościową, więc
// uszkodzony frontmatter cicho psuje wyszukiwanie — pre-screen przepuszcza wszystko albo nic.
// Dlatego zapis jest odrzucany, gdy YAML się nie parsuje lub brakuje pól krytycznych.
//
// Każdy zapis odkłada poprzednią wersję do /app/state/criteria-history. Kryteria zmieniają się
// często i bywa, że zmiana pogarsza wyniki — powrót do poprzedniej wersji ma być jednym kliknięciem,
// a nie szukaniem w pamięci.
import { existsSync, mkdirSync, readFileSync, writeFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { PROJECT_DIR } from './runner';

const FILE = join(PROJECT_DIR, 'properties', 'criteria.md');
const HISTORY_DIR = join(process.env.STATE_DIR || '/app/state', 'criteria-history');
const KEEP = 20;

export function readCriteria(): { text: string; mtime: number | null } {
  if (!existsSync(FILE)) return { text: '', mtime: null };
  return { text: readFileSync(FILE, 'utf-8'), mtime: statSync(FILE).mtimeMs };
}

/** Frontmatter = blok między pierwszymi '---'. Zwraca surowy YAML albo null. */
function frontmatter(text: string): string | null {
  const m = /^---\n([\s\S]*?)\n---\n/.exec(text);
  return m ? m[1] : null;
}

export type Validation = { ok: boolean; error?: string; summary?: string };

/**
 * Walidacja bez zależności od biblioteki YAML po stronie Node: sprawdzamy obecność
 * frontmattera i pól, bez których pipeline nie ma sensu. Pełne parsowanie robi Python
 * (skrypty i tak czytają ten plik PyYAML-em) — tu chodzi o wyłapanie oczywistej katastrofy,
 * a nie o duplikowanie parsera.
 */
export function validate(text: string): Validation {
  const fm = frontmatter(text);
  if (!fm) return { ok: false, error: 'Brak bloku frontmattera (--- na początku i końcu).' };

  const missing: string[] = [];
  for (const key of ['locations', 'area_min', 'price_max']) {
    if (!new RegExp(`^${key}\\s*:`, 'm').test(fm)) missing.push(key);
  }
  if (missing.length) {
    return { ok: false, error: `Brak pól krytycznych we frontmatterze: ${missing.join(', ')}. ` +
      'Bez nich pre-screen nie odsieje ofert.' };
  }

  // tabulatory to najczęstsza przyczyna niewidocznego błędu YAML
  if (/^\t/m.test(fm)) {
    return { ok: false, error: 'Frontmatter zawiera tabulatory — YAML wymaga spacji.' };
  }

  const locCount = (fm.match(/^\s*-\s*\{?\s*name\s*:/gm) || []).length;
  const body = text.slice((frontmatter(text) || '').length);
  return {
    ok: true,
    summary: `${locCount} lokalizacji, ${Math.round(body.length / 1024)} kB opisu`,
  };
}

function snapshot(reason: string): void {
  if (!existsSync(FILE)) return;
  if (!existsSync(HISTORY_DIR)) mkdirSync(HISTORY_DIR, { recursive: true });
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  writeFileSync(join(HISTORY_DIR, `${stamp}__${reason}.md`), readFileSync(FILE, 'utf-8'), 'utf-8');

  // przycinamy historię, żeby katalog nie puchł w nieskończoność
  const files = readdirSync(HISTORY_DIR).filter((f) => f.endsWith('.md')).sort();
  for (const f of files.slice(0, Math.max(0, files.length - KEEP))) {
    try { writeFileSync(join(HISTORY_DIR, f), ''); } catch { /* ignorujemy */ }
  }
}

export function writeCriteria(text: string, reason = 'edycja'): Validation {
  const v = validate(text);
  if (!v.ok) return v;
  snapshot(reason);
  writeFileSync(FILE, text, 'utf-8');
  return v;
}

export function listHistory(): { name: string; size: number; mtime: number }[] {
  if (!existsSync(HISTORY_DIR)) return [];
  return readdirSync(HISTORY_DIR)
    .filter((f) => f.endsWith('.md'))
    .map((f) => {
      const st = statSync(join(HISTORY_DIR, f));
      return { name: f, size: st.size, mtime: st.mtimeMs };
    })
    .filter((f) => f.size > 0)
    .sort((a, b) => b.mtime - a.mtime);
}

export function readHistory(name: string): string | null {
  // tylko nazwa pliku — żadnych ścieżek względnych z zewnątrz
  if (!/^[\w\-.:]+\.md$/.test(name)) return null;
  const p = join(HISTORY_DIR, name);
  return existsSync(p) ? readFileSync(p, 'utf-8') : null;
}
