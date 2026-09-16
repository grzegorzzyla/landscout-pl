import type { APIRoute } from 'astro';
import { checkPassword, signSession, SESSION_COOKIE } from '../../../server/auth';

export const prerender = false;

// Logowanie wspólnym hasłem. Po sukcesie: podpisana sesja w cookie na 30 dni.
//
// Przyjmujemy DWA formaty: JSON (strona wysyła fetchem) i formData (zapas, gdy JS jest wyłączony).
// JSON jest domyślny, bo ochrona CSRF Astro (security.checkOrigin) blokuje natywne POST-y
// formularzy, gdy nagłówek Origin nie zgadza się z Host — a tak bywa za mapowaniem portów
// w Dockerze i za proxy. Wyłączanie checkOrigin globalnie byłoby gorsze: straciłaby ochronę
// cała reszta strony, a problem dotyczy jednego formularza.
export const POST: APIRoute = async ({ request, cookies, redirect }) => {
  const isJson = (request.headers.get('content-type') || '').includes('application/json');
  let pw: unknown = '';
  if (isJson) {
    pw = (await request.json().catch(() => ({})) as any)?.password;
  } else {
    pw = (await request.formData()).get('password');
  }
  if (!checkPassword(typeof pw === 'string' ? pw : '')) {
    await new Promise((r) => setTimeout(r, 600)); // lekkie spowolnienie prób zgadywania
    return isJson
      ? new Response(JSON.stringify({ ok: false }), { status: 401, headers: { 'content-type': 'application/json' } })
      : redirect('/login?e=1', 302);
  }
  cookies.set(SESSION_COOKIE, signSession('ok'), {
    path: '/', httpOnly: true, sameSite: 'lax', maxAge: 60 * 60 * 24 * 30,
  });
  return isJson
    ? new Response(JSON.stringify({ ok: true }), { headers: { 'content-type': 'application/json' } })
    : redirect('/', 302);
};
