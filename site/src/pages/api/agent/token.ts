import type { APIRoute } from 'astro';
import { saveToken, clearToken, storedToken, authSource } from '../../../server/claude-auth';

export const prerender = false;

// Rotacja tokenu Claude Code bez przebudowy kontenera. Token trafia do pliku na wolumenie
// (prawa 0600), a procesy agentury czytają go przy uruchomieniu — patrz claudeEnv().
//
// Endpoint jest za bramką sesji (middleware), więc nie dokładamy osobnego uwierzytelnienia.
// Tokenu NIE zwracamy nigdy z powrotem — tylko informację, czy jest ustawiony.
export const POST: APIRoute = async ({ request }) => {
  const body = (await request.json().catch(() => ({}))) as { token?: string; action?: string };

  if (body.action === 'clear') {
    clearToken();
    return new Response(JSON.stringify({ ok: true, hasToken: false, source: authSource() }), {
      headers: { 'content-type': 'application/json' },
    });
  }

  const token = (body.token ?? '').trim();
  if (token.length < 20) {
    return new Response(JSON.stringify({ ok: false, error: 'Token wygląda na niekompletny' }), {
      status: 400, headers: { 'content-type': 'application/json' },
    });
  }
  saveToken(token);
  return new Response(JSON.stringify({ ok: true, hasToken: !!storedToken(), source: authSource() }), {
    headers: { 'content-type': 'application/json' },
  });
};
