import type { APIRoute } from 'astro';
import { runChatTurn, newSessionId, type ChatEvent } from '../../../server/chat';

export const prerender = false;

// Zmiana kryteriów poleceniem w języku naturalnym. Strumień SSE, jak w czacie — użytkownik ma
// widzieć, CO agent robi z plikiem, a nie dostać sam komunikat "gotowe".
//
// Prompt celowo wymusza dwie rzeczy: zachowanie struktury (frontmatter napędza pre-screen,
// proza napędza ocenę) i wypisanie na końcu, co zostało zmienione — inaczej trzeba by
// porównywać plik ręcznie, żeby się dowiedzieć.
export const POST: APIRoute = async ({ request }) => {
  const b = (await request.json().catch(() => ({}))) as { instruction?: string };
  const instruction = (b.instruction ?? '').trim();
  if (!instruction) {
    return new Response(JSON.stringify({ ok: false, error: 'Napisz, co zmienić' }), {
      status: 400, headers: { 'content-type': 'application/json' },
    });
  }

  const prompt =
    'Zmodyfikuj plik properties/criteria.md zgodnie z poleceniem użytkownika. ' +
    `POLECENIE: ${instruction}\n\n` +
    'Zasady: zachowaj strukturę pliku (frontmatter YAML + proza opisu). Frontmatter napędza ' +
    'pre-screen (locations, area_min, price_max), proza napędza ocenę jakościową — zmieniaj to, ' +
    'czego dotyczy polecenie, i nie przepisuj reszty bez potrzeby. Jeśli polecenie tworzy ' +
    'sprzeczność z istniejącym zapisem, rozwiąż ją i powiedz o tym. ' +
    'Na koniec wypisz zwięźle, co dokładnie zmieniłeś.';

  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    async start(controller) {
      const send = (e: ChatEvent) => {
        try { controller.enqueue(encoder.encode(`data: ${JSON.stringify(e)}\n\n`)); } catch { /* rozłączony */ }
      };
      await runChatTurn(prompt, newSessionId(), true, send);
      try { controller.close(); } catch { /* już zamknięty */ }
    },
  });

  return new Response(stream, {
    headers: {
      'content-type': 'text/event-stream; charset=utf-8',
      'cache-control': 'no-cache, no-transform',
      connection: 'keep-alive',
      'x-accel-buffering': 'no',
    },
  });
};
