import type { APIRoute } from 'astro';
import { startClaudeJob } from '../../server/runner';

export const prerender = false;

/**
 * Czy to strona WYNIKÓW (lista ofert), a nie pojedyncze ogłoszenie?
 *
 * Rozpoznajemy per portal i w razie wątpliwości mówimy "nie" — pomyłka w tę stronę kończy się
 * nieudanym ingestem jednej oferty, a w drugą: zleceniem wielogodzinnego skanu dla jednej działki.
 */
function isResultsPage(raw: string): boolean {
  let u: URL;
  try { u = new URL(raw); } catch { return false; }
  const host = u.hostname.replace(/^www\./, '').toLowerCase();
  const p = u.pathname.toLowerCase();
  if (host.endsWith('otodom.pl')) return p.includes('/wyniki/');
  if (host.endsWith('olx.pl')) return !p.includes('/oferta/') && p.startsWith('/d/nieruchomosci');
  if (host.endsWith('morizon.pl')) return !p.includes('/oferta/') && /^\/(dzialki|domy|nieruchomosci)\//.test(p);
  if (host.endsWith('adresowo.pl')) return !p.startsWith('/o/') && /^\/(f|dzialki|domy)\//.test(p);
  if (host.endsWith('gethome.pl')) return !p.includes('/oferta/') && /^\/(dzialki|domy)\//.test(p);
  return false;
}

/**
 * Skan całej strony wyników: listing → pre-screen → ingest tylko rokujących → ocena.
 * Ten sam pipeline co w properties-search, ale źródłem kandydatów jest WKLEJONY adres,
 * a nie lokalizacje z criteria.md — filtry portalu (powierzchnia, cena, region) są już w adresie.
 */
function scanPrompt(url: string): string {
  return (
    `Skanowanie STRONY WYNIKÓW (nie pojedynczej oferty): "${url}".\n` +
    `Przejdź pełny pipeline z CLAUDE.md, w tej kolejności:\n` +
    `1. LISTING — zbierz kandydatów z tego adresu. Otodom: ` +
    `PYTHONIOENCODING=utf-8 python3 scripts/scrape_otodom.py --search-url "${url}" --max 200 ` +
    `(skrypt sam paginuje od pierwszej strony i bierze filtry z adresu). Inny portal: użyj jego ` +
    `scrapera, a gdy nie przyjmuje gotowego adresu — odczytaj ze strony linki do ofert.\n` +
    `2. PRE-SCREEN — scripts/prescreen_candidates.py --candidates-file <plik z listingu>. ` +
    `Do ingestu idzie WYŁĄCZNIE "kept"; podaj potem, co i ile odpadło (meta.dropped).\n` +
    `3. INGEST — scripts/ingest_listing.py --urls-file <plik z linkami "kept">. ` +
    `Pomiń to, co już jest na liście lub w deleted/ (manage_listing.py known-sources).\n` +
    `4. OCENA — skill properties-eval na PEŁNYCH danych z .md. Status nowej oferty nadaje werdykt: ` +
    `dopasowane→watch, do-weryfikacji→active, odrzucone→delete.\n` +
    `Budżet: jeśli kandydatów jest więcej niż 60, weź najpierw najlepiej rokujące i zaznacz to w podsumowaniu.\n` +
    `Na samym końcu wypisz w OSTATNIEJ linii wyłącznie czysty JSON bez komentarza: ` +
    `{"ok":true,"found":<kandydatów z listingu>,"kept":<po pre-screenie>,"added":<dopisanych>} ` +
    `albo {"ok":false,"error":"<powód>"}.`
  );
}

// Ręczne dodanie oferty z linku — przez SKILL Claude Code (properties-ingest), nie surowy skrypt:
// agent umie zareagować, gdy ingest się posypie (blokada portalu, zmiana struktury karty).
// Wklejony adres strony wyników uruchamia zamiast tego skan całej listy.
export const POST: APIRoute = async ({ request }) => {
  try {
    const { url } = await request.json();
    if (!url || !/^https?:\/\//i.test(url)) {
      return new Response(JSON.stringify({ ok: false, error: 'Podaj poprawny link http(s)' }), { status: 400 });
    }

    if (isResultsPage(url)) {
      const jobId = startClaudeJob('search', `skan strony wyników: ${url}`, scanPrompt(url));
      return new Response(
        JSON.stringify({ ok: true, jobId, mode: 'scan', label: 'Skanuję stronę wyników (to potrwa)' }),
        { headers: { 'content-type': 'application/json' } },
      );
    }

    const prompt =
      `Ręczne dodanie oferty ze strony. Użyj skilla properties-ingest, aby zczytać PEŁNĄ kartę oferty ` +
      `z linku "${url}" do pliku .md z parametrem --added-by user (pełna galeria). ` +
      `Jeśli ingest się nie powiedzie (blokada/zmiana struktury/zły wariant URL), zdiagnozuj i spróbuj ` +
      `naprawić (np. inny format URL, ponów). ` +
      `Na samym końcu wypisz w OSTATNIEJ linii wyłącznie czysty JSON bez komentarza: ` +
      `{"ok":true,"id":"<id_oferty>","created":<true|false>} albo {"ok":false,"error":"<powód>"}.`;
    const jobId = startClaudeJob('ingest', `dodanie z linku: ${url}`, prompt);
    return new Response(JSON.stringify({ ok: true, jobId, mode: 'ingest' }), {
      headers: { 'content-type': 'application/json' },
    });
  } catch (e: any) {
    return new Response(JSON.stringify({ ok: false, error: e.message }), { status: 500 });
  }
};
