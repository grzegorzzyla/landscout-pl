import type { APIRoute } from 'astro';
import { runManage } from '../../server/runner';

export const prerender = false;

// Notatki oferty (dodaj/edytuj/usuń) — deterministyczne, przez manage_listing.py.
export const POST: APIRoute = async ({ request }) => {
  try {
    const { id, action, noteId, text } = await request.json();
    if (!id) return new Response(JSON.stringify({ ok: false, error: 'Brak id' }), { status: 400 });

    let res;
    if (action === 'add') {
      if (!text?.trim()) return new Response(JSON.stringify({ ok: false, error: 'Pusta notatka' }), { status: 400 });
      res = runManage(['note-add', '--id', id, '--text', text]);
    } else if (action === 'edit') {
      if (!noteId || !text?.trim()) return new Response(JSON.stringify({ ok: false, error: 'Brak noteId/treści' }), { status: 400 });
      res = runManage(['note-edit', '--id', id, '--note-id', noteId, '--text', text]);
    } else if (action === 'delete') {
      if (!noteId) return new Response(JSON.stringify({ ok: false, error: 'Brak noteId' }), { status: 400 });
      res = runManage(['note-delete', '--id', id, '--note-id', noteId]);
    } else {
      return new Response(JSON.stringify({ ok: false, error: 'Zła akcja' }), { status: 400 });
    }
    return new Response(JSON.stringify({ ok: true, ...res }), { headers: { 'content-type': 'application/json' } });
  } catch (e: any) {
    return new Response(JSON.stringify({ ok: false, error: e.message }), { status: 500 });
  }
};
