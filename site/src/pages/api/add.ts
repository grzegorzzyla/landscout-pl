import type { APIRoute } from 'astro';
import { startClaudeJob } from '../../server/runner';

export const prerender = false;

// Ręczne dodanie oferty z linku — przez SKILL Claude Code (properties-ingest), nie surowy skrypt:
// agent umie zareagować, gdy ingest się posypie (blokada portalu, zmiana struktury karty).
export const POST: APIRoute = async ({ request }) => {
  try {
    const { url } = await request.json();
    if (!url || !/^https?:\/\//i.test(url)) {
      return new Response(JSON.stringify({ ok: false, error: 'Podaj poprawny link http(s)' }), { status: 400 });
    }
    const prompt =
      `Ręczne dodanie oferty ze strony. Użyj skilla properties-ingest, aby zczytać PEŁNĄ kartę oferty ` +
      `z linku "${url}" do pliku .md z parametrem --added-by user (pełna galeria). ` +
      `Jeśli ingest się nie powiedzie (blokada/zmiana struktury/zły wariant URL), zdiagnozuj i spróbuj ` +
      `naprawić (np. inny format URL, ponów). ` +
      `Na samym końcu wypisz w OSTATNIEJ linii wyłącznie czysty JSON bez komentarza: ` +
      `{"ok":true,"id":"<id_oferty>","created":<true|false>} albo {"ok":false,"error":"<powód>"}.`;
    const jobId = startClaudeJob('ingest', `dodanie z linku: ${url}`, prompt);
    return new Response(JSON.stringify({ ok: true, jobId }), {
      headers: { 'content-type': 'application/json' },
    });
  } catch (e: any) {
    return new Response(JSON.stringify({ ok: false, error: e.message }), { status: 500 });
  }
};
