import type { APIRoute } from 'astro';
import { getJob } from '../../../server/runner';

export const prerender = false;

// Status zadania w tle (do pollingu z UI). Zwraca skróconą postać + ogon logu.
export const GET: APIRoute = async ({ params }) => {
  const job = getJob(params.id!);
  if (!job) return new Response(JSON.stringify({ ok: false, error: 'Nieznane zadanie' }), { status: 404 });
  return new Response(
    JSON.stringify({
      ok: true,
      id: job.id,
      kind: job.kind,
      status: job.status,
      label: job.label,
      listingId: job.listingId,
      result: job.result,
      error: job.error,
      tail: job.output.slice(-1200),
      startedAt: job.startedAt,
      finishedAt: job.finishedAt,
    }),
    { headers: { 'content-type': 'application/json' } },
  );
};
