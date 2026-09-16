import type { APIRoute } from 'astro';
import { readFileSync, existsSync } from 'node:fs';
import { logPath, getTask } from '../../../server/queue';

export const prerender = false;

// Dziennik zadania. Zwracamy OGON pliku — pełne wyjście agenta potrafi mieć megabajty,
// a w panelu i tak interesuje nas koniec (wynik albo miejsce, w którym się wywrócił).
export const GET: APIRoute = async ({ url }) => {
  const id = url.searchParams.get('id') || '';
  const task = getTask(id);
  if (!task) {
    return new Response(JSON.stringify({ ok: false, error: 'Nie ma takiego zadania' }), {
      status: 404, headers: { 'content-type': 'application/json' },
    });
  }
  const p = logPath(id);
  let text = existsSync(p) ? readFileSync(p, 'utf-8') : '(dziennik jeszcze pusty)';
  const LIMIT = 40000;
  if (text.length > LIMIT) text = '… (początek pominięty) …\n' + text.slice(-LIMIT);
  return new Response(JSON.stringify({ ok: true, task, log: text }), {
    headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
  });
};
