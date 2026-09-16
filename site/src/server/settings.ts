// Ustawienia działania agentury, zmieniane z panelu i trwałe między restartami.
// Osobno od zmiennych środowiskowych: te ostatnie opisują ŚRODOWISKO (adresy, klucze),
// a to są decyzje użytkownika, które ma móc przestawić bez redeployu stacku.
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const STATE_DIR = process.env.STATE_DIR || '/app/state';
const FILE = join(STATE_DIR, 'settings.json');

export type Settings = {
  /** Ocena ofert lokalnym modelem zamiast Claude (patrz scripts/eval_local.py). */
  localEval: boolean;
};

const DEFAULTS: Settings = { localEval: false };

export function readSettings(): Settings {
  try {
    return { ...DEFAULTS, ...JSON.parse(readFileSync(FILE, 'utf-8')) };
  } catch {
    return { ...DEFAULTS };
  }
}

export function writeSettings(patch: Partial<Settings>): Settings {
  if (!existsSync(STATE_DIR)) mkdirSync(STATE_DIR, { recursive: true });
  const next = { ...readSettings(), ...patch };
  writeFileSync(FILE, JSON.stringify(next, null, 1), 'utf-8');
  return next;
}

/** Konfiguracja lokalnego modelu pochodzi ze środowiska — panel tylko włącza/wyłącza jej użycie. */
export function localLlm(): { url: string; model: string; configured: boolean } {
  const url = process.env.LOCAL_LLM_URL || '';
  const model = process.env.LOCAL_LLM_MODEL || 'local';
  return { url, model, configured: !!url };
}
