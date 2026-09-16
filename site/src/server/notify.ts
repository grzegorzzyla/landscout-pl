// Powiadomienia o zakończonych zadaniach agentury.
//
// Trzy kanały obsłużone równolegle, bo różnią się kompromisem, a nie jakością:
//   • Discord  — najprościej: jeden webhook, zero zakładania czegokolwiek
//   • Telegram — bot + chat_id, za to wygodne na telefonie i niezależne od serwera domowego
//   • ntfy     — publiczne ntfy.sh działa zza NAT-u (NAS tylko wysyła), a własna instancja
//                w tailnecie nie wypuszcza treści na zewnątrz
// Włączasz ustawiając zmienne; nieustawione kanały są po prostu pomijane. Brak konfiguracji
// nie jest błędem — powiadomienia są dodatkiem, nie warunkiem działania kolejki.
const TIMEOUT_MS = 10000;

export type Channel = { name: string; configured: boolean };

export function channels(): Channel[] {
  return [
    { name: 'Discord', configured: !!process.env.DISCORD_WEBHOOK_URL },
    { name: 'Telegram', configured: !!(process.env.TELEGRAM_BOT_TOKEN && process.env.TELEGRAM_CHAT_ID) },
    { name: 'ntfy', configured: !!process.env.NTFY_URL },
  ];
}

async function post(url: string, init: RequestInit): Promise<void> {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), TIMEOUT_MS);
  try {
    const r = await fetch(url, { ...init, signal: ctl.signal });
    if (!r.ok) console.error(`[powiadomienia] ${new URL(url).host} odpowiedział ${r.status}`);
  } catch (e: any) {
    // Powiadomienie, które nie doszło, NIE może wywalić zadania — logujemy i idziemy dalej.
    console.error(`[powiadomienia] błąd wysyłki: ${e?.message ?? e}`);
  } finally {
    clearTimeout(t);
  }
}

/** Wysyła na wszystkie skonfigurowane kanały. Nigdy nie rzuca. */
export async function notify(title: string, body: string): Promise<void> {
  const text = `${title}\n${body}`.trim();
  const jobs: Promise<void>[] = [];

  const discord = process.env.DISCORD_WEBHOOK_URL;
  if (discord) {
    jobs.push(post(discord, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      // 2000 znaków to twardy limit Discorda — ucinamy sami, żeby nie dostać 400
      body: JSON.stringify({ content: text.slice(0, 1900) }),
    }));
  }

  const tgToken = process.env.TELEGRAM_BOT_TOKEN;
  const tgChat = process.env.TELEGRAM_CHAT_ID;
  if (tgToken && tgChat) {
    jobs.push(post(`https://api.telegram.org/bot${tgToken}/sendMessage`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ chat_id: tgChat, text: text.slice(0, 4000), disable_web_page_preview: true }),
    }));
  }

  const ntfy = process.env.NTFY_URL;
  if (ntfy) {
    const headers: Record<string, string> = {
      Title: title.replace(/[\r\n]/g, ' ').slice(0, 200),
      // nagłówki ntfy muszą być ASCII — polskie znaki w tytule psują wysyłkę
      ...(process.env.NTFY_TOKEN ? { Authorization: `Bearer ${process.env.NTFY_TOKEN}` } : {}),
    };
    headers.Title = headers.Title.normalize('NFKD').replace(/[^\x20-\x7E]/g, '');
    jobs.push(post(ntfy, { method: 'POST', headers, body: body.slice(0, 3900) }));
  }

  await Promise.all(jobs);
}
