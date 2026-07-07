import type { APIRoute } from 'astro';
import { listJobs } from '../../server/runner';

export const prerender = false;

// Lista zadań w tle (Claude Code) — do wskaźnika w rogu strony.
export const GET: APIRoute = async () => {
  const jobs = listJobs().slice(0, 30).map((j) => ({
    id: j.id, kind: j.kind, label: j.label, status: j.status,
    listingId: j.listingId, startedAt: j.startedAt, finishedAt: j.finishedAt,
    added: j.result && typeof j.result.added === 'number' ? j.result.added : null,
  }));
  const running = jobs.filter((j) => j.status === 'running').length;
  return new Response(JSON.stringify({ ok: true, running, jobs }), {
    headers: { 'content-type': 'application/json' },
  });
};
