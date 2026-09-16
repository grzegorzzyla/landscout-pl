import type { APIRoute } from 'astro';
import { notify, channels } from '../../../server/notify';

export const prerender = false;

export const GET: APIRoute = async () =>
  new Response(JSON.stringify({ channels: channels() }), {
    headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
  });

// Wysyłka próbna — jedyny sposób sprawdzenia konfiguracji bez czekania na nocne zadanie.
export const POST: APIRoute = async () => {
  const cfg = channels().filter((c) => c.configured);
  if (!cfg.length) {
    return new Response(JSON.stringify({ ok: false, error: 'Żaden kanał nie jest skonfigurowany' }), {
      status: 400, headers: { 'content-type': 'application/json' },
    });
  }
  await notify('LandScout — test', 'Jeśli to widzisz, powiadomienia działają.');
  return new Response(JSON.stringify({ ok: true, sent: cfg.map((c) => c.name) }), {
    headers: { 'content-type': 'application/json' },
  });
};
