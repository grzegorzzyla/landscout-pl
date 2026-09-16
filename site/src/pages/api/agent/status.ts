import type { APIRoute } from 'astro';
import { collectStatus } from '../../../server/agent';

export const prerender = false;

// Stan agentury. Kontrole uruchamiają realne procesy (m.in. start Chromium), więc odpowiedź
// potrafi zająć kilkanaście sekund — strona pokazuje to jako ładowanie.
export const GET: APIRoute = async () => {
  const data = collectStatus();
  return new Response(JSON.stringify(data), {
    headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
  });
};
