import type { APIRoute } from 'astro';
import { enqueue, listTasks, cancel, startScheduler, nextNight } from '../../../server/queue';

export const prerender = false;

// Zegar startuje przy pierwszym dotknięciu API — Astro nie ma haka „po starcie serwera",
// a strona i tak odpytuje kolejkę po wejściu do panelu.
startScheduler();

export const GET: APIRoute = async () =>
  new Response(JSON.stringify({ tasks: listTasks(30), nextNight: nextNight() }), {
    headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
  });

export const POST: APIRoute = async ({ request }) => {
  const b = (await request.json().catch(() => ({}))) as {
    kind?: string; note?: string; when?: string; cancelId?: string;
  };

  if (b.cancelId) {
    return new Response(JSON.stringify({ ok: cancel(b.cancelId) }), {
      headers: { 'content-type': 'application/json' },
    });
  }

  const kind = b.kind === 'fb-scan' ? 'fb-scan' : 'search';
  const when = b.when === 'now' ? 'now' : 'night';
  const t = enqueue(kind, b.note ?? '', when);
  return new Response(JSON.stringify({ ok: true, task: t }), {
    headers: { 'content-type': 'application/json' },
  });
};
