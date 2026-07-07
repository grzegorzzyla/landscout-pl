import type { APIRoute } from 'astro';
import { checkPassword, signSession, SESSION_COOKIE } from '../../../server/auth';

export const prerender = false;

// Logowanie wspólnym hasłem. Po sukcesie: podpisana sesja w cookie na 30 dni.
export const POST: APIRoute = async ({ request, cookies, redirect }) => {
  const form = await request.formData();
  const pw = form.get('password');
  if (!checkPassword(typeof pw === 'string' ? pw : '')) {
    await new Promise((r) => setTimeout(r, 600)); // lekkie spowolnienie prób zgadywania
    return redirect('/login?e=1', 302);
  }
  cookies.set(SESSION_COOKIE, signSession('ok'), {
    path: '/', httpOnly: true, sameSite: 'lax', maxAge: 60 * 60 * 24 * 30,
  });
  return redirect('/', 302);
};
