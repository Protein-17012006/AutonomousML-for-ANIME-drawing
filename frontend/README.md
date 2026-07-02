# Frontend — In-Between Co-pilot (Next.js)

The artist-facing UI. Next.js 16 (App Router) + React 19 + Tailwind 4 + shadcn/ui.
Replaces the earlier Vite SPA; the co-pilot logic (session SSE, timing-sheet review
board, grounded Q&A) was ported into `src/components/copilot/`.

## Routes
- `/` → redirects to `/copilot`.
- `/copilot` → the chat-first co-pilot (client-only SPA): drop keys/video → streamed
  decision log as chat bubbles → flagged/needs-key bubbles → result card + review board,
  plus grounded follow-up Q&A (`POST /session/{sid}/ask`).

## Dev
```bash
npm install
npm run dev            # http://localhost:3000
```
Dev proxies the API to the box: `next.config.ts` rewrites `/session`, `/session/:path*`,
`/demo` → `NEXT_PUBLIC_API_TARGET` (default `http://100.71.161.102:8000`).

## Production (static export, served by the FastAPI service)
```bash
BUILD_EXPORT=1 npm run build     # -> out/  (static, trailingSlash)
```
`out/` is served same-origin by the co-pilot service via `COPILOT_WEB_DIR` (same slot as
the old Vite `dist/`) — so no rewrites are needed in prod (relative `/session` fetches hit
the same origin). Deployed live on the box `:8000`.

> Deploy note: `scripts/deploy_box.sh` still does `cd frontend && npm run build` expecting a
> Vite `dist/`. For this app, build with `BUILD_EXPORT=1 npm run build` and ship `out/`
> (→ `COPILOT_WEB_DIR`). Update the script when wiring the Next flow into deploy tooling.
