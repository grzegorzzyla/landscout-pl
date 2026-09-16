// Kolejka zadań agentury z terminem wykonania.
//
// Świadomie NIE cron: wyszukiwanie ma się odpalać wtedy, gdy TY je zlecisz — z terminem „w nocy"
// albo „teraz" — a nie co dobę niezależnie od tego, czy coś się zmieniło. Nocne okno ma znaczenie
// praktyczne: ocena ofert to najdroższy element (rzędu milionów tokenów), a limit jest wspólny
// z sesjami w edytorze; uruchomienie po północy daje największą szansę, że rano okno jest wolne.
//
// Stan leży na wolumenie (/app/state), żeby kolejka i dzienniki przeżyły restart kontenera.
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, writeFileSync, readdirSync, createWriteStream } from 'node:fs';
import { join } from 'node:path';
import { PROJECT_DIR, resolveClaudeExeCached } from './runner';
import { claudeEnv } from './claude-auth';
import { notify } from './notify';
import { readSettings, localLlm } from './settings';

const STATE_DIR = process.env.STATE_DIR || '/app/state';
const JOBS_DIR = join(STATE_DIR, 'jobs');
const LOGS_DIR = join(STATE_DIR, 'logs');

export type TaskKind = 'search' | 'fb-scan';
export type TaskStatus = 'queued' | 'running' | 'done' | 'error' | 'cancelled';

export type Task = {
  id: string;
  kind: TaskKind;
  note: string;              // co użytkownik chciał (wolny tekst dopisywany do polecenia)
  status: TaskStatus;
  runAt: number;             // kiedy ma ruszyć (ms)
  createdAt: number;
  startedAt?: number;
  finishedAt?: number;
  summary?: string;          // ostatnie linie wyjścia — do pokazania w panelu
  error?: string;
};

function ensureDirs(): void {
  for (const d of [STATE_DIR, JOBS_DIR, LOGS_DIR]) {
    if (!existsSync(d)) mkdirSync(d, { recursive: true });
  }
}

function taskPath(id: string): string { return join(JOBS_DIR, `${id}.json`); }
export function logPath(id: string): string { return join(LOGS_DIR, `${id}.log`); }

function save(t: Task): void {
  ensureDirs();
  writeFileSync(taskPath(t.id), JSON.stringify(t, null, 1), 'utf-8');
}

export function getTask(id: string): Task | null {
  try {
    return JSON.parse(readFileSync(taskPath(id), 'utf-8')) as Task;
  } catch {
    return null;
  }
}

export function listTasks(limit = 50): Task[] {
  ensureDirs();
  return readdirSync(JOBS_DIR)
    .filter((f) => f.endsWith('.json'))
    .map((f) => { try { return JSON.parse(readFileSync(join(JOBS_DIR, f), 'utf-8')) as Task; } catch { return null; } })
    .filter((t): t is Task => !!t)
    .sort((a, b) => b.createdAt - a.createdAt)
    .slice(0, limit);
}

/** Najbliższa noc: dziś o NIGHT_HOUR, a gdy ta godzina już minęła — jutro. */
const NIGHT_HOUR = Number(process.env.NIGHT_HOUR ?? 3);
export function nextNight(): number {
  const d = new Date();
  d.setHours(NIGHT_HOUR, 0, 0, 0);
  if (d.getTime() <= Date.now()) d.setDate(d.getDate() + 1);
  return d.getTime();
}

export function enqueue(kind: TaskKind, note: string, when: 'now' | 'night'): Task {
  const t: Task = {
    id: `${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
    kind,
    note: note.trim(),
    status: 'queued',
    runAt: when === 'now' ? Date.now() : nextNight(),
    createdAt: Date.now(),
  };
  save(t);
  tick();  // gdy „teraz", nie czekamy na najbliższy przebieg zegara
  return t;
}

export function cancel(id: string): boolean {
  const t = getTask(id);
  if (!t || t.status !== 'queued') return false;
  t.status = 'cancelled';
  t.finishedAt = Date.now();
  save(t);
  return true;
}

// --- wykonywanie ---------------------------------------------------------------------

let running: string | null = null;

/** Polecenie dla agenta. Skille robią resztę — tu tylko intencja i ograniczniki. */
function buildPrompt(t: Task): string {
  if (t.kind === 'fb-scan') {
    return 'Użyj skilla properties-search w trybie "skanuj grupy FB". ' +
      (t.note ? `Uwagi użytkownika: ${t.note}. ` : '') +
      'Na koniec podaj jednym zdaniem: ile postów przeczytano i ile ofert dopisano.';
  }
  // Gdy włączona ocena lokalnym modelem, podmieniamy TYLKO etap scoringu — orkiestracja,
  // ingest i deep-dive zostają przy Claude, bo tam małe modele zawodzą.
  const llm = localLlm();
  const local = readSettings().localEval && llm.configured
    ? 'Do etapu OCENY NIE używaj skilla properties-eval ani agentów — zamiast tego uruchom ' +
      `scripts/eval_local.py (lokalny model, ${llm.model}) na pełnych rekordach z .md, ` +
      'a wynik zapisz tak samo jak przy ocenie standardowej. Pozostałe etapy bez zmian. '
    : '';

  return 'Użyj skilla properties-search: pełne wyszukiwanie wg properties/criteria.md, ' +
    'tryb autonomiczny (sam dopisz trafione). ' +
    local +
    (t.note ? `Dodatkowe uwagi użytkownika: ${t.note}. ` : '') +
    'Po ocenie uruchom properties-deep-dive dla ofert z werdyktem "dopasowane" — bez tego ' +
    'ranking opiera się wyłącznie na opisach sprzedających. ' +
    'Na koniec podaj jednym zdaniem: ile ofert znaleziono, ile dopisano, ile odrzucono.';
}

function runTask(t: Task): void {
  ensureDirs();
  running = t.id;
  t.status = 'running';
  t.startedAt = Date.now();
  save(t);

  const log = createWriteStream(logPath(t.id), { flags: 'a' });
  log.write(`=== ${new Date().toISOString()} start: ${t.kind} ${t.note ? '(' + t.note + ')' : ''}\n`);

  let exe: string;
  try {
    exe = resolveClaudeExeCached();
  } catch (e: any) {
    t.status = 'error';
    t.error = e?.message ?? 'Nie znaleziono Claude Code';
    t.finishedAt = Date.now();
    save(t);
    log.end(`BŁĄD: ${t.error}\n`);
    running = null;
    return;
  }

  const child = spawn(
    exe,
    ['-p', buildPrompt(t), '--dangerously-skip-permissions', '--output-format', 'text'],
    { cwd: PROJECT_DIR, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true, env: claudeEnv() },
  );

  let tail = '';
  const onData = (d: Buffer) => {
    const s = d.toString();
    log.write(s);
    tail = (tail + s).slice(-4000);        // trzymamy tylko ogon — pełne wyjście jest w pliku
    // Limit tokenów potrafi uciąć zadanie w środku nocy; zapisujemy to wprost, żeby rano
    // było widać przyczynę, a nie tylko "błąd".
    if (/rate.?limit|usage limit|resets at/i.test(s)) {
      log.write('\n[kolejka] wykryto komunikat o limicie użycia\n');
    }
  };
  child.stdout.on('data', onData);
  child.stderr.on('data', onData);

  child.on('error', (e) => {
    t.status = 'error';
    t.error = e.message;
    t.finishedAt = Date.now();
    save(t);
    log.end(`\nBŁĄD uruchomienia: ${e.message}\n`);
    running = null;
    tick();
  });

  child.on('close', (code) => {
    t.finishedAt = Date.now();
    t.summary = tail.trim().split('\n').filter(Boolean).slice(-4).join(' ').slice(0, 500);
    if (code === 0) {
      t.status = 'done';
    } else {
      t.status = 'error';
      t.error = `Claude Code zakończył się kodem ${code}`;
    }
    save(t);
    log.end(`\n=== ${new Date().toISOString()} koniec: ${t.status}\n`);

    // Powiadomienie wysyłamy PO zapisie stanu i bez czekania — kanał może być niedostępny,
    // a to nie powód, żeby blokować kolejkę.
    const mins = t.startedAt ? Math.round((t.finishedAt! - t.startedAt) / 60000) : 0;
    const what = t.kind === 'search' ? 'Wyszukiwanie' : 'Skan grup FB';
    void notify(
      t.status === 'done' ? `✅ ${what} zakończone` : `⚠️ ${what} nie powiodło się`,
      [
        t.note ? `Uwagi: ${t.note}` : '',
        `Czas: ${mins} min`,
        t.summary || t.error || '',
      ].filter(Boolean).join('\n'),
    );

    running = null;
    tick();
  });
}

/** Sprawdza, czy jest co uruchomić. Wołane z zegara i po dodaniu zadania „teraz". */
export function tick(): void {
  if (running) return;
  const due = listTasks(200)
    .filter((t) => t.status === 'queued' && t.runAt <= Date.now())
    .sort((a, b) => a.runAt - b.runAt);
  if (due.length) runTask(due[0]);
}

let timer: NodeJS.Timeout | null = null;
export function startScheduler(): void {
  if (timer) return;
  ensureDirs();
  // Po restarcie kontenera zadania „running" są osierocone — proces nie przeżył. Oznaczamy je
  // jako błąd, inaczej kolejka stałaby zablokowana w nieskończoność.
  for (const t of listTasks(200)) {
    if (t.status === 'running') {
      t.status = 'error';
      t.error = 'przerwane restartem kontenera';
      t.finishedAt = Date.now();
      save(t);
    }
  }
  timer = setInterval(tick, 60_000);
  tick();
}
