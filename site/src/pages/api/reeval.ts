import type { APIRoute } from 'astro';
import { startClaudeJob, findRunningJob } from '../../server/runner';

export const prerender = false;

// Ponowna ocena oferty (np. po zmianie notatki) — przez Claude Code / skill properties-eval,
// z UWZGLĘDNIENIEM notatek użytkownika. Zapisuje score + sekcję ## Ocena dopasowania.
// Jedna re-ocena na ofertę naraz — kolejne zmiany notatek podpinają się pod trwające zadanie (bez mnożenia).
export const POST: APIRoute = async ({ request }) => {
  try {
    const { id, reason } = await request.json();
    if (!id) return new Response(JSON.stringify({ ok: false, error: 'Brak id' }), { status: 400 });
    const existing = findRunningJob('reeval', id);
    if (existing) {
      return new Response(JSON.stringify({ ok: true, jobId: existing.id, alreadyRunning: true }), {
        headers: { 'content-type': 'application/json' },
      });
    }
    const why = reason ? ` (powód: ${reason})` : '';
    const prompt =
      `Ponowna ocena oferty "${id}"${why}. To zadanie ZAPISUJĄCE — wykonaj WSZYSTKIE kroki, nie zatrzymuj ` +
      `się na samej ocenie:\n` +
      `1. Przeczytaj properties/criteria.md (OPIS poszukiwanej działki).\n` +
      `2. \`python scripts/manage_listing.py get --id ${id}\` — weź description, pola ORAZ notes[]. ` +
      `Notatki użytkownika są WIARYGODNIEJSZE niż opis sprzedającego i mają realny wpływ na ocenę.\n` +
      `3. Oceń dopasowanie do kryteriów (możesz użyć skilla properties-eval): score 0-100, werdykt ` +
      `(dopasowane|do-weryfikacji|odrzucone), 1 zdanie reason — UWZGLĘDNIJ notatki.\n` +
      `4. OBOWIĄZKOWO ZAPISZ wynik (bez tego zadanie jest nieukończone):\n` +
      `   - zapamiętaj stary score; \`python scripts/manage_listing.py set --id ${id} --field score --value <nowy_score>\`\n` +
      `   - zapisz plik z treścią "**Ocena: <score>/100 — <werdykt>** (po notatce, <data>)\\n\\n<reason>" i ` +
      `\`python scripts/manage_listing.py set-section --id ${id} --header "Ocena dopasowania" --text-file <plik>\`\n` +
      `   - dopisz do historii: \`python scripts/manage_listing.py log --id ${id} --text "ponowna ocena (notatka): score <nowy> (było <stary>)"\`\n` +
      `5. **STATUSU NIE ZMIENIAJ** — to istniejąca oferta, re-ocena rusza tylko score/ocenę/datę, nie status.\n` +
      `6. Na samym końcu wypisz w OSTATNIEJ linii TYLKO czysty JSON: {"ok":true,"id":"${id}","score":<liczba>} ` +
      `(albo {"ok":false,"error":"..."}). NIE kończ na tablicy z oceny — wynik MUSI być zapisany w krokach 4.`;
    const jobId = startClaudeJob('reeval', `ponowna ocena: ${id}`, prompt, id);
    return new Response(JSON.stringify({ ok: true, jobId }), {
      headers: { 'content-type': 'application/json' },
    });
  } catch (e: any) {
    return new Response(JSON.stringify({ ok: false, error: e.message }), { status: 500 });
  }
};
