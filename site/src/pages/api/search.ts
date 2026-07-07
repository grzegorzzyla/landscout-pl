import type { APIRoute } from 'astro';
import { startClaudeJob } from '../../server/runner';

export const prerender = false;

// „Szukaj w sieci" — uruchamia skill properties-search (tryb autonomiczny) przez Claude Code.
// Skill: listing → ingest pełnych kart → ocena → dopisanie nowych ≥ progu. Zwraca liczbę dodanych.
export const POST: APIRoute = async ({ request }) => {
  try {
    let uwagi = '';
    try {
      const body = await request.json();
      if (body && typeof body.uwagi === 'string') uwagi = body.uwagi.trim();
    } catch {
      /* brak/niepoprawne body — uruchom bez uwag */
    }
    const prompt =
      `Uruchom skill properties-search w trybie autonomicznym. ` +
      (uwagi
        ? `UWAGI UŻYTKOWNIKA (zinterpretuj je w Kroku wejściowym skilla — mogą zmienić lokalizacje, ` +
          `portale, działka/dom, zasięg, akcenty jakościowe albo tryb pracy): „${uwagi}". `
        : ``) +
      `Przeszukaj portale wg kryteriów (properties/criteria.md) z uwzględnieniem powyższych uwag, ` +
      `zczytaj pełne karty (ingest), oceń i rozdysponuj wg werdyktu. Pomiń duplikaty już na liście (i skasowane). ` +
      `Na samym końcu wypisz w OSTATNIEJ linii wyłącznie czysty JSON bez komentarza: ` +
      `{"ok":true,"added":<liczba nowo dodanych ofert>} albo {"ok":false,"error":"<powód>"}.`;
    const label = uwagi ? `szukanie w sieci: ${uwagi.slice(0, 40)}` : 'szukanie w sieci (properties-search)';
    const jobId = startClaudeJob('search', label, prompt);
    return new Response(JSON.stringify({ ok: true, jobId }), {
      headers: { 'content-type': 'application/json' },
    });
  } catch (e: any) {
    return new Response(JSON.stringify({ ok: false, error: e.message }), { status: 500 });
  }
};
