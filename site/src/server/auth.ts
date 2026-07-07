// Prosta bramka: wspólne hasło dostępu + podpisana sesja (cookie). Bez kont, bez kluczy zewnętrznych.
// Server-only. Konfiguracja z .env (Astro ładuje do import.meta.env).
import crypto from 'node:crypto';

const env = (k: string): string =>
  (import.meta.env?.[k] as string) ?? process.env[k] ?? '';

const PASSWORD = env('ACCESS_PASSWORD');
const SECRET = env('SESSION_SECRET') || 'dev-insecure-secret-change-me';

export const SESSION_COOKIE = 'sess';
export const passwordConfigured = () => Boolean(PASSWORD);

export function checkPassword(pw: string | null | undefined): boolean {
  if (!PASSWORD || !pw) return false;
  const a = Buffer.from(String(pw));
  const b = Buffer.from(PASSWORD);
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

// --- sesja: podpisany token w cookie --------------------------------------
const b64 = (s: string | Buffer) => Buffer.from(s).toString('base64url');
const hmac = (data: string) => crypto.createHmac('sha256', SECRET).update(data).digest('base64url');

export function signSession(sub = 'ok'): string {
  const payload = b64(JSON.stringify({ sub, exp: Date.now() + 30 * 864e5 }));
  return payload + '.' + hmac(payload);
}

export function verifySession(token: string | undefined): string | null {
  if (!token) return null;
  const [payload, sig] = token.split('.');
  if (!payload || !sig) return null;
  const expected = hmac(payload);
  if (sig.length !== expected.length ||
      !crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(expected))) return null;
  try {
    const o = JSON.parse(Buffer.from(payload, 'base64url').toString());
    if (!o.sub || o.exp < Date.now()) return null;
    return o.sub as string;
  } catch {
    return null;
  }
}
