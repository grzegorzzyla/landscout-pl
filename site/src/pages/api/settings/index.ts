import type { APIRoute } from 'astro';
import { readSettings, writeSettings, localLlm } from '../../../server/settings';

export const prerender = false;

export const GET: APIRoute = async () =>
  new Response(JSON.stringify({ settings: readSettings(), localLlm: localLlm() }), {
    headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
  });

export const POST: APIRoute = async ({ request }) => {
  const b = (await request.json().catch(() => ({}))) as { localEval?: boolean };
  const s = writeSettings({ localEval: !!b.localEval });
  return new Response(JSON.stringify({ ok: true, settings: s, localLlm: localLlm() }), {
    headers: { 'content-type': 'application/json' },
  });
};
