import type { APIRoute } from 'astro';
import { startClaudeJob, findRunningJob } from '../../server/runner';

export const prerender = false;

// Wyzwolenie pogłębionej analizy (properties-deep-dive) przez Claude Code headless.
// Można uruchomić ponownie (skill/dane mogły się zmienić), ale NIE równolegle dla tej samej oferty —
// wielokrotne kliknięcie „deep-dive"/„Ulubione" podpina się pod trwające zadanie zamiast mnożyć procesy.
export const POST: APIRoute = async ({ request }) => {
  try {
    const { id, favorite } = await request.json();
    if (!id) return new Response(JSON.stringify({ ok: false, error: 'Brak id' }), { status: 400 });
    const existing = findRunningJob('deepdive', id);
    if (existing) {
      return new Response(JSON.stringify({ ok: true, jobId: existing.id, alreadyRunning: true }), {
        headers: { 'content-type': 'application/json' },
      });
    }
    const favNote = favorite
      ? `Oferta została właśnie oznaczona jako Ulubiona — to wyzwolenie deep-dive. `
      : '';
    const prompt =
      `${favNote}Użyj skilla properties-deep-dive dla oferty o id "${id}". ` +
      `Wykonaj pełną pogłębioną analizę (geoportal/ULDK, NMT, odległości, oględziny zdjęć) i zapisz wynik ` +
      `do sekcji "## Analiza pogłębiona" oraz pola deep_dive (data/historia) przez manage_listing.py. ` +
      `Uruchom analizę nawet jeśli była już wcześniej (odśwież ją). ` +
      `Na końcu wypisz w OSTATNIEJ linii wyłącznie czysty JSON: ` +
      `{"ok":true,"id":"${id}"} albo {"ok":false,"error":"<powód>"}.`;
    const jobId = startClaudeJob('deepdive', `deep-dive: ${id}`, prompt, id);
    return new Response(JSON.stringify({ ok: true, jobId }), {
      headers: { 'content-type': 'application/json' },
    });
  } catch (e: any) {
    return new Response(JSON.stringify({ ok: false, error: e.message }), { status: 500 });
  }
};
