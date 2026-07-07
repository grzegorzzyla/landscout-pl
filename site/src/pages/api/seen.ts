import type { APIRoute } from 'astro';
import { runManage } from '../../server/runner';

export const prerender = false;

// Oznacz ofertę jako obejrzaną (wywoływane przy otwarciu karty). Deterministyczne.
export const POST: APIRoute = async ({ request }) => {
  try {
    const { id } = await request.json();
    if (!id) return new Response(JSON.stringify({ ok: false, error: 'Brak id' }), { status: 400 });
    runManage(['seen', '--id', id]);
    return new Response(JSON.stringify({ ok: true }), { headers: { 'content-type': 'application/json' } });
  } catch (e: any) {
    return new Response(JSON.stringify({ ok: false, error: e.message }), { status: 500 });
  }
};
