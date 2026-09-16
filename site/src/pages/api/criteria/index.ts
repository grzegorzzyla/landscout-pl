import type { APIRoute } from 'astro';
import { readCriteria, writeCriteria, validate, listHistory, readHistory } from '../../../server/criteria';

export const prerender = false;

export const GET: APIRoute = async ({ url }) => {
  const hist = url.searchParams.get('history');
  if (hist) {
    const text = readHistory(hist);
    return new Response(JSON.stringify(text === null ? { ok: false } : { ok: true, text }), {
      headers: { 'content-type': 'application/json' },
    });
  }
  const { text, mtime } = readCriteria();
  return new Response(JSON.stringify({ ok: true, text, mtime, history: listHistory() }), {
    headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
  });
};

export const POST: APIRoute = async ({ request }) => {
  const b = (await request.json().catch(() => ({}))) as { text?: string; check?: boolean };
  const text = b.text ?? '';

  // Sam podgląd walidacji — pozwala ostrzec w edytorze, zanim ktoś kliknie zapis.
  if (b.check) {
    return new Response(JSON.stringify(validate(text)), {
      headers: { 'content-type': 'application/json' },
    });
  }

  const v = writeCriteria(text, 'edycja-www');
  return new Response(JSON.stringify(v), {
    status: v.ok ? 200 : 400,
    headers: { 'content-type': 'application/json' },
  });
};
