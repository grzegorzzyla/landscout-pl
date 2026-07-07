import { defineMiddleware } from 'astro:middleware';
import { verifySession, SESSION_COOKIE } from './server/auth';

// Bramka dostępu: wszystko wymaga zalogowanej sesji, POZA stroną /login, endpointami /api/auth/*
// i zasobami statycznymi. Strony bez sesji → redirect na /login; API bez sesji → 401.
const PUBLIC = [/^\/login\/?$/, /^\/api\/auth\//];
const ASSET = [/^\/_/, /^\/photos\//, /^\/favicon/, /\.(css|js|mjs|png|jpe?g|webp|svg|ico|woff2?|map)$/i];

export const onRequest = defineMiddleware(async (ctx, next) => {
  const path = ctx.url.pathname;
  if (ASSET.some((r) => r.test(path)) || PUBLIC.some((r) => r.test(path))) return next();

  const sess = verifySession(ctx.cookies.get(SESSION_COOKIE)?.value);
  if (!sess) {
    if (path.startsWith('/api/')) {
      return new Response(JSON.stringify({ ok: false, error: 'Wymagane logowanie' }), {
        status: 401, headers: { 'content-type': 'application/json' },
      });
    }
    return ctx.redirect('/login', 302);
  }
  return next();
});
