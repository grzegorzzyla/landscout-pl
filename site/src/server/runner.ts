// Backend strony działek: uruchamianie skili Claude Code headless (zadania w tle z monitorowaniem)
// oraz deterministycznych skryptów Pythona (status/notatki). Server-only (Node) — używane przez /api/*.
import { spawn, execFileSync } from 'node:child_process';
import { readdirSync, existsSync } from 'node:fs';
import { join, dirname, basename } from 'node:path';
import os from 'node:os';

// Katalog projektu (rdzeń: skille w .claude/, skrypty w scripts/, dane w properties/).
// Domyślnie katalog nadrzędny względem site/ (strona uruchamiana z site/); nadpisywalny przez ASSISTANT_DIR.
export const PROJECT_DIR =
  process.env.ASSISTANT_DIR ||
  (basename(process.cwd()) === 'site' ? dirname(process.cwd()) : process.cwd());

export type Job = {
  id: string;
  kind: 'ingest' | 'deepdive' | 'search' | 'reeval';
  status: 'running' | 'done' | 'error';
  label: string;
  output: string;
  result: any | null;
  error: string | null;
  listingId: string | null;
  startedAt: number;
  finishedAt: number | null;
};

// Stan zadań trzymany w pamięci procesu dev-serwera (jeden proces) — wystarcza do pollingu z UI.
const jobs = new Map<string, Job>();
let seq = 0;

export function getJob(id: string): Job | undefined {
  return jobs.get(id);
}

// Lista zadań (najnowsze pierwsze) — do wskaźnika procesów w tle w UI.
export function listJobs(): Job[] {
  return [...jobs.values()].sort((a, b) => b.startedAt - a.startedAt);
}

// Znajdź trwające zadanie danego rodzaju dla danej oferty — do blokady duplikatów
// (np. wielokrotne kliknięcie „deep-dive"/„Ulubione" nie ma odpalać kolejnych procesów).
export function findRunningJob(kind: Job['kind'], listingId: string): Job | undefined {
  return [...jobs.values()].find((j) => j.status === 'running' && j.kind === kind && j.listingId === listingId);
}

// Ścieżka do Claude Code (NIE Claude Desktop). Jedno źródło prawdy = launcher bin/cdp w repo
// (`cdp --which`); gdy niedostępny, fallback na lokalne rozwiązanie. Sam prompt przekazujemy potem
// binarce bezpośrednio przez argv (bez powłoki) — patrz startClaudeJob.
function resolveViaCdp(): string | null {
  try {
    const isWin = process.platform === 'win32';
    const script = join(PROJECT_DIR, 'bin', isWin ? 'cdp.ps1' : 'cdp');
    if (!existsSync(script)) return null;
    const out = isWin
      ? execFileSync('powershell',
          ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', script, '--which'],
          { encoding: 'utf-8' })
      : execFileSync(script, ['--which'], { encoding: 'utf-8' });
    const p = (out.trim().split(/\r?\n/).pop() || '').trim();
    return p && existsSync(p) ? p : null;
  } catch {
    return null;
  }
}

function resolveClaudeExe(): string {
  if (process.env.CLAUDE_EXE && existsSync(process.env.CLAUDE_EXE)) return process.env.CLAUDE_EXE;
  const viaCdp = resolveViaCdp();
  if (viaCdp) return viaCdp;
  // Fallback gdy cdp nie zadziałał. UWAGA: ścieżka %APPDATA% istnieje tylko na Windowsie — na macOS/Linux
  // sklejała się w bezsensowne ~/AppData/Roaming/... i taki komunikat trafiał do użytkownika.
  if (process.platform !== 'win32') {
    const candidates = [
      join(os.homedir(), '.claude', 'local', 'claude'),
      join(os.homedir(), '.local', 'bin', 'claude'),
      '/opt/homebrew/bin/claude',
      '/usr/local/bin/claude',
    ];
    for (const c of candidates) if (existsSync(c)) return c;
    // Binarka rozszerzenia edytora bywa jedyną na maszynie (gdy ktoś używa Claude Code tylko z IDE).
    // Katalog zawiera numer wersji, więc bierzemy najnowszy.
    for (const extRoot of ['.vscode/extensions', '.vscode-insiders/extensions',
                           '.cursor/extensions', '.windsurf/extensions']) {
      const dir = join(os.homedir(), ...extRoot.split('/'));
      if (!existsSync(dir)) continue;
      const hit = readdirSync(dir)
        .filter((d) => d.startsWith('anthropic.claude-code-'))
        .sort()
        .reverse()
        .map((d) => join(dir, d, 'resources', 'native-binary', 'claude'))
        .find((f) => existsSync(f));
      if (hit) return hit;
    }
    throw new Error('Nie znaleziono Claude Code. Ustaw CLAUDE_EXE albo zainstaluj CLI (`claude`).');
  }
  const base = join(os.homedir(), 'AppData', 'Roaming', 'Claude', 'claude-code');
  if (!existsSync(base)) throw new Error('Nie znaleziono Claude Code (ustaw CLAUDE_EXE lub sprawdź bin/cdp): ' + base);
  const cmp = (a: string, b: string) => {
    const pa = a.split('.').map(Number), pb = b.split('.').map(Number);
    for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
      const d = (pb[i] || 0) - (pa[i] || 0);
      if (d) return d;
    }
    return 0;
  };
  const vers = readdirSync(base)
    .filter((d) => existsSync(join(base, d, 'claude.exe')))
    .sort(cmp);
  if (!vers.length) throw new Error('claude.exe nie znaleziony w ' + base);
  return join(base, vers[0], 'claude.exe');
}

// Uruchom skill Claude Code headless jako zadanie w tle. Prompt instruuje agenta, by wywołał skill
// i na końcu wypisał JSON w ostatniej linii. Zwraca jobId (UI poll-uje /api/job/<id>).
export function startClaudeJob(kind: Job['kind'], label: string, prompt: string, listingId: string | null = null): string {
  const id = `${Date.now()}_${++seq}`;
  const job: Job = {
    id, kind, status: 'running', label, output: '', result: null, error: null,
    listingId, startedAt: Date.now(), finishedAt: null,
  };
  jobs.set(id, job);

  let exe: string;
  try {
    exe = resolveClaudeExe();
  } catch (e: any) {
    job.status = 'error';
    job.error = e.message;
    job.finishedAt = Date.now();
    return id;
  }

  const child = spawn(
    exe,
    ['-p', prompt, '--dangerously-skip-permissions', '--output-format', 'text'],
    { cwd: PROJECT_DIR, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true },
  );
  child.stdout.on('data', (d) => (job.output += d.toString()));
  child.stderr.on('data', (d) => (job.output += d.toString()));
  child.on('error', (e) => {
    job.status = 'error';
    job.error = e.message;
    job.finishedAt = Date.now();
  });
  child.on('close', (code) => {
    job.finishedAt = Date.now();
    // ostatni blok {...} w wyjściu = ustrukturyzowany wynik od agenta
    const m = job.output.trim().match(/\{[\s\S]*\}\s*$/);
    if (m) {
      try {
        job.result = JSON.parse(m[0]);
        if (job.result?.id) job.listingId = String(job.result.id);
      } catch {}
    }
    if (code === 0 && job.result?.ok !== false) {
      job.status = 'done';
    } else {
      job.status = 'error';
      job.error = job.result?.error || `Claude Code zakończył się kodem ${code}`;
    }
  });
  return id;
}

// Interpreter Pythona nie jest ten sam na każdej maszynie: na macOS/Linux `python` bywa innym
// (systemowym) Pythonem niż ten, do którego pip zainstalował zależności — wtedy skrypty wywracają się
// na `ModuleNotFoundError: No module named 'yaml'`. Na Windowsie zwykle jest odwrotnie i `python3`
// nie istnieje. Dlatego wybieramy interpreter, który REALNIE importuje yaml, i cache'ujemy wynik.
let _pythonExe: string | null = null;
export function pythonExe(): string {
  if (_pythonExe) return _pythonExe;
  const candidates = [process.env.PYTHON_EXE, 'python3', 'python'].filter(Boolean) as string[];
  for (const exe of candidates) {
    try {
      execFileSync(exe, ['-c', 'import yaml, httpx'], { stdio: 'ignore' });
      _pythonExe = exe;
      return exe;
    } catch {
      /* próbuj kolejny */
    }
  }
  throw new Error(
    'Nie znaleziono Pythona z zależnościami (yaml, httpx). Zainstaluj: ' +
    'pip install -r scripts/requirements.txt — albo wskaż interpreter zmienną PYTHON_EXE.',
  );
}

// Deterministyczne wywołanie manage_listing.py (status/notatki) — synchronicznie, zwraca sparsowany JSON.
export function runManage(args: string[]): any {
  const out = execFileSync(pythonExe(), ['scripts/manage_listing.py', ...args], {
    cwd: PROJECT_DIR,
    encoding: 'utf-8',
    env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
  });
  const last = out.trim().split('\n').pop() || '';
  try {
    return JSON.parse(last);
  } catch {
    return { raw: out };
  }
}
