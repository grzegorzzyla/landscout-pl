import type { APIRoute } from 'astro';
import { runManage } from '../../server/runner';

export const prerender = false;

const ALLOWED = ['active', 'inactive', 'favorite', 'watch'];

// Zmiana statusu oferty — deterministyczne, bez Claude Code.
export const POST: APIRoute = async ({ request }) => {
  try {
    const { id, status } = await request.json();
    if (!id || !ALLOWED.includes(status)) {
      return new Response(JSON.stringify({ ok: false, error: 'Brak id lub zły status' }), { status: 400 });
    }
    const res = runManage(['set-status', '--id', id, '--status', status]);
    return new Response(JSON.stringify({ ok: true, ...res }), {
      headers: { 'content-type': 'application/json' },
    });
  } catch (e: any) {
    return new Response(JSON.stringify({ ok: false, error: e.message }), { status: 500 });
  }
};
