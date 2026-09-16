import type { APIRoute } from 'astro';
import { runChatTurn, newSessionId, type ChatEvent } from '../../server/chat';

export const prerender = false;

// Czat z agenturą. Odpowiedź to strumień SSE — tura rozmowy trwa od kilku sekund do kilku minut
// (agent potrafi uruchamiać scrapery i deep-dive), więc zwykły JSON po zakończeniu oznaczałby
// minuty wpatrywania się w pustą stronę.
//
// JSON zamiast formularza: ochrona CSRF Astro (security.checkOrigin) blokuje POST-y formularzy,
// gdy Origin nie zgadza się z Host — tak jak przy logowaniu.
export const POST: APIRoute = async ({ request }) => {
  const body = (await request.json().catch(() => ({}))) as {
    message?: string;
    sessionId?: string | null;
  };
  const message = (body.message ?? '').trim();
  if (!message) {
    return new Response(JSON.stringify({ ok: false, error: 'Pusta wiadomość' }), {
      status: 400, headers: { 'content-type': 'application/json' },
    });
  }

  const isFirstTurn = !body.sessionId;
  const sessionId = body.sessionId || newSessionId();

  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    async start(controller) {
      const send = (e: ChatEvent) => {
        try {
          controller.enqueue(encoder.encode(`data: ${JSON.stringify(e)}\n\n`));
        } catch {
          /* klient się rozłączył */
        }
      };
      // Identyfikator sesji leci PIERWSZY, żeby przeglądarka mogła go zapamiętać nawet wtedy,
      // gdy tura zakończy się błędem — inaczej kolejna wiadomość zaczynałaby rozmowę od zera.
      send({ type: 'session', sessionId });
      await runChatTurn(message, sessionId, isFirstTurn, send);
      try {
        controller.close();
      } catch {
        /* już zamknięty */
      }
    },
  });

  return new Response(stream, {
    headers: {
      'content-type': 'text/event-stream; charset=utf-8',
      'cache-control': 'no-cache, no-transform',
      connection: 'keep-alive',
      // wyłącza buforowanie w ewentualnym proxy — bez tego strumień dochodzi hurtem na końcu
      'x-accel-buffering': 'no',
    },
  });
};
