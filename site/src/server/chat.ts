// Czat z agenturą: uruchamia Claude Code w trybie strumieniowym i tłumaczy jego NDJSON
// na proste zdarzenia dla przeglądarki.
//
// Dlaczego CLI, a nie Agent SDK: cała agentura (skille properties-*, CLAUDE.md, uprawnienia)
// jest już skonfigurowana pod Claude Code. Uruchomienie tej samej binarki daje czatowi dostęp
// do wyszukiwania, oceny i deep-dive bez duplikowania konfiguracji.
//
// Ciągłość rozmowy trzyma sam Claude Code: pierwsza tura dostaje --session-id <uuid>, kolejne
// --resume <uuid>. Historia leży w ~/.claude (wolumen claude-home), więc przeżywa restart kontenera.
import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { PROJECT_DIR, resolveClaudeExeCached } from './runner';
import { claudeEnv } from './claude-auth';

export type ChatEvent =
  | { type: 'session'; sessionId: string }
  | { type: 'text'; text: string }        // fragment odpowiedzi (strumieniowo)
  | { type: 'tool'; name: string; info: string }
  | { type: 'limit'; text: string }       // zużycie okna limitu / odmowa
  | { type: 'done'; ok: boolean; error?: string };

export function newSessionId(): string {
  return randomUUID();
}

/** Krótki, czytelny opis wywołania narzędzia — pełne argumenty bywają ogromne (całe pliki). */
function describeTool(name: string, input: any): string {
  if (!input || typeof input !== 'object') return '';
  const pick = (k: string) => (typeof input[k] === 'string' ? input[k] : '');
  const raw =
    pick('command') || pick('file_path') || pick('pattern') || pick('url') ||
    pick('prompt') || pick('description') || pick('skill') || '';
  const oneline = raw.replace(/\s+/g, ' ').trim();
  return oneline.length > 160 ? oneline.slice(0, 160) + '…' : oneline;
}

/**
 * Uruchamia jedną turę rozmowy. `onEvent` dostaje zdarzenia na bieżąco.
 * Zwraca obietnicę spełnianą po zakończeniu procesu.
 */
export function runChatTurn(
  message: string,
  sessionId: string,
  isFirstTurn: boolean,
  onEvent: (e: ChatEvent) => void,
): Promise<void> {
  return runTurn(message, sessionId, isFirstTurn, onEvent, true);
}

function runTurn(
  message: string,
  sessionId: string,
  isFirstTurn: boolean,
  onEvent: (e: ChatEvent) => void,
  mayRetry: boolean,
): Promise<void> {
  return new Promise((resolve) => {
    let exe: string;
    try {
      exe = resolveClaudeExeCached();
    } catch (e: any) {
      onEvent({ type: 'done', ok: false, error: e?.message || 'Nie znaleziono Claude Code' });
      return resolve();
    }

    const args = [
      '-p', message,
      '--output-format', 'stream-json',
      '--verbose',
      '--include-partial-messages',
      '--dangerously-skip-permissions',
      ...(isFirstTurn ? ['--session-id', sessionId] : ['--resume', sessionId]),
    ];

    const child = spawn(exe, args, {
      cwd: PROJECT_DIR,
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
      env: claudeEnv(),   // token wymieniony w panelu działa od razu, bez redeployu
    });

    let buf = '';
    let sawError = '';

    child.stdout.on('data', (chunk: Buffer) => {
      buf += chunk.toString();
      // NDJSON: jedna wiadomość na linię; ostatni, niepełny fragment zostaje w buforze
      const lines = buf.split('\n');
      buf = lines.pop() ?? '';
      for (const line of lines) {
        const t = line.trim();
        if (!t) continue;
        let msg: any;
        try {
          msg = JSON.parse(t);
        } catch {
          continue; // niekompletny/nieoczekiwany wiersz — pomijamy
        }
        translate(msg, onEvent);
      }
    });

    child.stderr.on('data', (d: Buffer) => {
      const s = d.toString();
      sawError += s;
      for (const line of s.split('\n')) {
        if (line.trim()) console.error(`[czat] ${line}`);
      }
    });

    child.on('error', (e) => {
      onEvent({ type: 'done', ok: false, error: e.message });
      resolve();
    });

    child.on('close', async (code) => {
      if (code === 0) {
        onEvent({ type: 'done', ok: true });
        return resolve();
      }

      // Wznowienie nieistniejącej sesji to sytuacja NAPRAWIALNA, nie błąd do pokazania:
      // zdarza się, gdy pierwsza tura padła (np. w trakcie przebudowy kontenera), a przeglądarka
      // zdążyła zapamiętać identyfikator. Bez tego każda kolejna wiadomość padałaby w nieskończoność.
      const looksLikeMissingSession = /no conversation|session.*(not found|does not exist)|resume/i
        .test(sawError);
      if (!isFirstTurn && mayRetry && looksLikeMissingSession) {
        const fresh = newSessionId();
        onEvent({ type: 'session', sessionId: fresh });
        console.error('[czat] wznowienie nieudane — zaczynam nową sesję');
        await runTurn(message, fresh, true, onEvent, false);
        return resolve();
      }

      onEvent({
        type: 'done',
        ok: false,
        error: sawError.trim().split('\n').slice(-3).join(' ') || `Claude Code zakończył się kodem ${code}`,
      });
      resolve();
    });
  });
}

/** Mapuje zdarzenia stream-json Claude Code na nasze proste zdarzenia. */
function translate(msg: any, onEvent: (e: ChatEvent) => void): void {
  // Strumień tokenów (z --include-partial-messages)
  if (msg.type === 'stream_event') {
    const ev = msg.event;
    if (ev?.type === 'content_block_delta' && ev.delta?.type === 'text_delta' && ev.delta.text) {
      onEvent({ type: 'text', text: ev.delta.text });
    }
    return;
  }

  // Pełne wiadomości asystenta: stąd bierzemy wywołania narzędzi
  if (msg.type === 'assistant' && msg.message?.content) {
    for (const block of msg.message.content) {
      if (block?.type === 'tool_use') {
        onEvent({ type: 'tool', name: block.name || 'narzędzie', info: describeTool(block.name, block.input) });
      }
    }
    return;
  }

  // CLI raportuje zużycie okna limitu. Czat dzieli je z sesjami w edytorze, więc warto wiedzieć
  // ZAWCZASU, że agentura zaraz zacznie odmawiać — zwłaszcza przy zadaniach z crona w tle.
  if (msg.type === 'rate_limit_event') {
    const info = msg.rate_limit_info || {};
    const win = info.unifiedWindows?.[info.rateLimitType] || {};
    const pct = typeof win.utilization === 'number' ? Math.round(win.utilization * 100) : null;
    if (info.status && info.status !== 'allowed') {
      onEvent({ type: 'limit', text: `limit wyczerpany (${info.rateLimitType ?? 'okno'})` +
        (win.resetsAt ? ` — odnowa ${new Date(win.resetsAt * 1000).toLocaleTimeString('pl-PL')}` : '') });
    } else if (pct !== null && pct >= 80) {
      onEvent({ type: 'limit', text: `uwaga: zużyto ${pct}% okna limitu` +
        (win.resetsAt ? ` (odnowa ${new Date(win.resetsAt * 1000).toLocaleTimeString('pl-PL')})` : '') });
    }
    return;
  }

  if (msg.type === 'system' && msg.session_id) {
    onEvent({ type: 'session', sessionId: String(msg.session_id) });
    return;
  }

  if (msg.type === 'result') {
    if (msg.is_error) {
      onEvent({ type: 'done', ok: false, error: String(msg.result ?? 'błąd agenta') });
    }
    // sukces sygnalizuje zamknięcie procesu — tu nie kończymy, żeby nie uciąć ostatnich zdarzeń
  }
}
