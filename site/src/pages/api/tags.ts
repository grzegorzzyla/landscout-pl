import type { APIRoute } from 'astro';
import { runManage } from '../../server/runner';

export const prerender = false;

// Tagi oferty — deterministyczne, przez manage_listing.py (zastępuje całą listę tagów).
export const POST: APIRoute = async ({ request }) => {
  try {
    const { id, tags } = await request.json();
    if (!id) return new Response(JSON.stringify({ ok: false, error: 'Brak id' }), { status: 400 });
    const list = (Array.isArray(tags) ? tags : []).map((t: any) => String(t).replace(/,/g, ' '));
    const res = runManage(['set-tags', '--id', id, '--tags', list.join(',')]);
    return new Response(JSON.stringify({ ok: true, ...res }), { headers: { 'content-type': 'application/json' } });
  } catch (e: any) {
    return new Response(JSON.stringify({ ok: false, error: e.message }), { status: 500 });
  }
};
