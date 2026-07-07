import { defineConfig } from 'astro/config';
import node from '@astrojs/node';

// Strona przeglądania działek + lekki backend (API routes) do mutacji i wyzwalania
// skili Claude Code. Dane czytane wprost z ../properties/listings (jedno źródło prawdy).
// Strony (index, /dzialka/[id]) są prerenderowane (w dev renderowane na żądanie z aktualnych .md);
// endpointy /api/* działają server-side (output: 'server'). Serwowanie dla telefonu: `npm run start`.
export default defineConfig({
  output: 'server',
  adapter: node({ mode: 'standalone' }),
  server: { host: true, port: 4321 },
  // Dev-serwer Vite blokuje nieznane nazwy hostów ("Blocked request"). Dodatkowe hosty (np. domena
  // tailnetu Tailscale dla dostępu z telefonu) podaj w env ALLOWED_HOSTS, po przecinku,
  // np. ALLOWED_HOSTS=.tail1234.ts.net,moj-host.example.com
  vite: {
    server: {
      allowedHosts: (process.env.ALLOWED_HOSTS ?? '')
        .split(',')
        .map((h) => h.trim())
        .filter(Boolean),
    },
  },
});
