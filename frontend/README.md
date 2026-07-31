# Frontend — In-Between Co-pilot (Next.js)

The artist-facing UI. Next.js 16 (App Router) + React 19 + Tailwind 4 + shadcn/ui.
Replaces the earlier Vite SPA; the co-pilot logic (session SSE, timing-sheet review
board, grounded Q&A) was ported into `src/components/copilot/`.

## Routes
- `/` → public, statically rendered landing page.
- `/copilot` → Cognito-protected chat-first co-pilot (client-only SPA): drop keys/video → streamed
  decision log as chat bubbles → flagged/needs-key bubbles → result card + review board,
  plus grounded follow-up Q&A (`POST /session/{sid}/ask`).
- `/login`, `/signup`, `/verify-email`, `/forgot-password`, `/reset-password`, and
  `/sso-callback` → Cognito/Amplify authentication flow.

## Authentication and persistence

Amplify obtains a Cognito ID token for a one-time `POST /auth/session` bootstrap. FastAPI
validates the token and sets an HttpOnly cookie; `/copilot` checks `/auth/me`, and later
API/SSE requests use same-origin credentials. Direct browser Identity Pool, DynamoDB, and S3
access has been removed. Conversation/message persistence is outside the current scope and retained
only as an optional future improvement. Durable session history is the supported product path: FastAPI can
list the signed-in user's published sessions through `GET /sessions` and stream an owned output
through `GET /sessions/{pid}/artifacts/{name}`. The browser never receives AWS credentials,
bucket names, raw object keys, or another user's Cognito `sub`.

## Dev
```bash
npm install
npm run dev            # http://localhost:3000
```
Dev proxies the API to the model-backed service: `next.config.ts` rewrites `/auth/:path*`,
`/me/:path*`, `/session`, `/session/:path*`, `/sessions`, and `/sessions/:path*` to `NEXT_PUBLIC_API_TARGET`
(default and `.env.example` target: `http://100.71.161.102:8000`). Override
`NEXT_PUBLIC_API_TARGET` only when deliberately testing another reachable backend.

For the no-model session-retrieval proof, configure these backend-only values in
`service/.env.local` and run `uvicorn service.auth_dev_app:app --reload --env-file service/.env.local`:

```dotenv
COPILOT_SESSION_HISTORY_ENABLED=1
AWS_SESSIONS_TABLE=copilot_sessions
AWS_ARTIFACT_BUCKET=copilot-g4-artifacts
AWS_SESSIONS_OWNER_INDEX=OwnerSessionsIndex
AWS_REGION=ap-southeast-1
```

Boto3 obtains AWS access from the server process's normal credential chain. Do not put AWS
credentials or these storage settings in `NEXT_PUBLIC_*`. After `/auth/me` succeeds on `/copilot`,
development builds request the first 20 owned session summaries and print them in the browser
console. Artifact bytes are fetched only when a protected artifact URL is requested; entering the
page does not download every artifact.

## Production (static export, served by the FastAPI service)
```bash
BUILD_EXPORT=1 npm run build     # -> out/  (static, trailingSlash)
```
`out/` is served same-origin by the co-pilot service via `COPILOT_WEB_DIR` (same slot as
the old Vite `dist/`) — so no rewrites are needed in prod (relative `/session` fetches hit
the same origin). Deployed live on the box `:8000`.

> Deploy note: `scripts/deploy_box.sh` intentionally syncs service code only; it does not deploy
> the canonical frontend export. Build with `BUILD_EXPORT=1 npm run build`, publish the contents
> of `out/` to the configured box web directory (`~/copilot_svc/dist` by default), then restart the
> service with `scripts/deploy_box.sh --restart` when service code also changed.
