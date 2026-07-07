import type { APIRoute } from 'astro';
import { SESSION_COOKIE } from '../../../server/auth';

export const prerender = false;

export const GET: APIRoute = async ({ cookies, redirect }) => {
  cookies.delete(SESSION_COOKIE, { path: '/' });
  return redirect('/login', 302);
};
