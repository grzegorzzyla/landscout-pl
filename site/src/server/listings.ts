// Odczyt ofert WPROST z dysku (properties/listings/*.md) na każde żądanie — bez content-layer cache,
// więc strona zawsze pokazuje aktualny stan zaraz po mutacji (status/notatki/deep-dive). Server-only.
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import matter from 'gray-matter';
import { marked } from 'marked';
import { PROJECT_DIR } from './runner';

const DIR = join(PROJECT_DIR, 'properties', 'listings');
const ID_RE = /^\d{8}_\d{3,}$/;

export type Listing = Record<string, any> & { id: string; _body: string };

export function readListing(id: string): Listing | null {
  if (!ID_RE.test(id)) return null;
  const p = join(DIR, id + '.md');
  if (!existsSync(p)) return null;
  const { data, content } = matter(readFileSync(p, 'utf-8'));
  return { ...data, id: data.id || id, _body: content };
}

export function readAllListings(): Listing[] {
  if (!existsSync(DIR)) return [];
  return readdirSync(DIR)
    .filter((f) => f.endsWith('.md') && ID_RE.test(f.slice(0, -3)))
    .map((f) => readListing(f.slice(0, -3)))
    .filter((x): x is Listing => x !== null);
}

export function renderMarkdown(md: string): string {
  return marked.parse(md || '', { async: false }) as string;
}
