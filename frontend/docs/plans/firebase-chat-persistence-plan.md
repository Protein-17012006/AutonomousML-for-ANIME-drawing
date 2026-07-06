# Firebase Persistence for the In-Between Co-pilot Chat — Design & Implementation Report

_Status: proposed (planning). Date: 2026-07-06 (rev. 2 — added re-run "Continue editing")._

## 1. Context & problem

The co-pilot conversation at `/copilot` is **ephemeral**. Its transcript is *derived* every render by
`deriveMessages({ upload, log, result, running, banner, qa: qaTurns })` in
`frontend/src/components/copilot/lib/chatModel.ts` — nothing is stored, and starting a new run **wipes**
the previous one. A page reload loses the whole session. Goal: **persist chat history + messages so past
conversations survive reload and are reopenable**.

Firebase is already scaffolded but **inert**:
- `frontend/src/lib/firebase.ts` — initializes and exports `db` (Firestore) + `auth` from `NEXT_PUBLIC_FIREBASE_*` env vars (project `cos30018-anime-ai-interface`).
- `frontend/src/lib/firestore.ts` — an 18-line **import-only stub** (implements nothing).
- `frontend/src/models/interfaces.ts` — `Message`/`Chat` types built for the *deleted* ChatGPT-style chat (do not fit the co-pilot).
- **No auth flow exists anywhere** (auth is initialized but never consumed).
- Prod is a **static export** (`BUILD_EXPORT=1` → `output: export`), so all Firestore/Storage/Auth must be **client-side** (browser SDK) — no route handlers, server actions, or Admin SDK.

## 2. Decisions (agreed with the user)

| Area | Decision |
|---|---|
| Frame images on restore | **Full fidelity** via **Firebase Storage** — upload key + in-between/annotated/montage PNGs (and recon video) and rewrite persisted URLs to permanent Storage URLs. |
| Identity | **Google sign-in** via Firebase Auth (greenfield). Co-pilot stays usable signed-out (ephemeral); saving/history requires sign-in. |
| History UI | **Collapsible left sidebar** listing past conversations + "New chat". |
| Types | `Message`/`Chat` may be freely redefined for the co-pilot. |

## 3. Core architecture — persist source state, re-derive on restore

Because the transcript is derived, we persist the **source state**, not the rendered messages. The
load-bearing mechanism is the **URL rewrite**: the *live* runtime state keeps the server
`/session/{sid}/…` URLs (so grounded Ask / draw-key Refill keep working), while the **saved copy** gets
permanent Storage URLs.

| Field | Live value | Persisted value |
|---|---|---|
| `upload.thumbs[]` | `blob:` URLs | Storage URLs |
| `log[i].mid_url` | `/session/{sid}/…` | Storage URL |
| `result.artifacts.{montage,video,report}` | `/session/{sid}/…` | Storage URLs |
| `result.explanations[k].annotated_url` | `/session/{sid}/…` | Storage URL |
| `result.pair_mids[k]` | `/session/{sid}/…` | Storage URL |
| `result.key_urls[k]` | present (video flow) / **absent (PNG flow)** | Storage URLs — **must synthesize for PNG flow** |

**Why the last row is critical:** on restore `keys.files` is empty, so `effKeyUrls`
(`CopilotApp.tsx:61-67`) falls back to `result.key_urls`. A PNG-upload session never receives server
`key_urls`, so the persist step must upload the client `keys.files` and populate
`result.key_urls = {0:url,1:url,…}`, or restored key/in-between/key triptychs render black. Storage
`getDownloadURL()` returns token-bearing URLs so `<img src>` reads without an auth header.

## 4. Data model

**Types** — in `frontend/src/models/interfaces.ts`, keep `FirebaseConfig`; replace `Message`/`Chat` with:

```ts
export type SessionKind = "png" | "video" | "planted";

// light doc that drives the sidebar list (never holds the heavy payload)
export interface ConversationMeta {
  id: string;
  title: string;
  kind: SessionKind;
  engines: string; fps: string; stride: string;
  sid: string | null;            // original server session id (reference only)
  uploadLabel: string;
  thumb?: string | null;         // first Storage thumb for the list row
  createdAt: number | null;      // serverTimestamp() -> read as millis
  updatedAt: number | null;
}

// heavy transcript payload (loaded only when a conversation is opened)
export interface ConversationState {
  upload: UserTurn | null;                              // from copilot/lib/chatModel
  log: PairEvent[];                                     // from copilot/types
  result: ResultEvent | null;                           // from copilot/types
  qaTurns: QaTurn[];                                    // from copilot/lib/chatModel
  verdicts: Record<string, "accept" | "reject">;        // numeric keys stringified by Firestore
}
```

**Firestore layout** (subcollection → simplest rules; isolates the 1 MB doc limit to the rarely-read state doc):

```
users/{uid}/conversations/{cid}            -> ConversationMeta   (list: onSnapshot, orderBy updatedAt desc)
users/{uid}/conversations/{cid}/state/main -> ConversationState  (loaded only on open)
```

**Storage layout:**

```
users/{uid}/conversations/{cid}/keys/{i}.png
users/{uid}/conversations/{cid}/mids/{index}.png
users/{uid}/conversations/{cid}/annotated/{index}.png
users/{uid}/conversations/{cid}/pair_mids/{index}.png
users/{uid}/conversations/{cid}/montage.png
users/{uid}/conversations/{cid}/video.mp4     (optional-but-preferred)
users/{uid}/conversations/{cid}/report.<ext>
```

## 5. Implementation phases

### Phase 1 — Firebase wiring
- **Edit `frontend/src/lib/firebase.ts`**: `export const storage = getStorage(app);`.
- **New `frontend/src/lib/auth.tsx`** (`"use client"`): `AuthProvider` context + `useAuth()` → `{ user, loading, signIn, signOut }`. `onAuthStateChanged` in a `useEffect`; `signIn` = `signInWithPopup(auth, new GoogleAuthProvider())` with `signInWithRedirect` fallback on `auth/popup-blocked`. Mirror the existing `ThemeProvider` context shape.
- **Edit `frontend/src/app/layout.tsx`**: wrap `{children}` in `<AuthProvider>` **inside** `<ThemeProvider>`.

### Phase 2 — Storage upload/rewrite → new `frontend/src/components/copilot/lib/persistImages.ts`
`persistSessionImages({ uid, cid, state, keyFiles, includeVideo=true, onProgress }): Promise<ConversationState>`:
1. Upload `keyFiles[i]` → `keys/{i}.png`; build `keyUrlMap`.
2. Collect every server URL (`mid_url`, `annotated_url`, `pair_mids`, `key_urls`, `artifacts.*`), dedupe, `fetch()`→blob→upload (same-origin in prod, dev-proxied → no CORS), build `serverUrlMap`.
3. Deep-clone `state`, rewrite all URL fields; for PNG flow set `result.key_urls = keyUrlMap` and `upload.thumbs` → key Storage URLs.

### Phase 3 — Firestore CRUD → implement `frontend/src/lib/firestore.ts` (drop the dead `Message/Chat/AIProvider` import)
`newConversationId(uid)`, `createConversation(uid,cid,meta,state)` (setDoc meta with `serverTimestamp()` + setDoc `state/main`), `updateConversationState(uid,cid,patch)` (merge state + touch meta.updatedAt), `getConversationState(uid,cid)`, `subscribeConversations(uid,cb): Unsubscribe` (onSnapshot ordered by updatedAt), `deleteConversation(uid,cid)` (best-effort Storage `listAll`+`deleteObject`). Coerce `verdicts` keys back to numbers on read; map `serverTimestamp` → millis (`data.updatedAt?.toMillis?.() ?? null`).

### Phase 4 — CopilotApp wiring → edit `frontend/src/components/copilot/CopilotApp.tsx`
- New state: `const { user } = useAuth()`, `cid`, `liveSid`, `conversations`, `saving`, `lastSavedRef`.
- **Track `liveSid`**: in each `onResult`, `setLiveSid(r.artifacts ? r.artifacts.montage.split("/")[2] : null)`. Rewrite `onAsk`/`refillKey` to use `liveSid` instead of re-parsing artifact URLs (post-restore those are Storage URLs and would 404). `clearAll()` also nulls `cid` + `liveSid`.
- **Subscribe**: `useEffect` → `subscribeConversations(user.uid, setConversations)` when signed in.
- **Save on run-complete** (`useEffect` on `[result, running, user]`, deduped by `result.artifacts.montage` via `lastSavedRef`): `persistSessionImages(...)` → `createConversation` / `updateConversationState`; show `saving`.
- **Light save** (`useEffect` on `[qaTurns, verdicts, cid]`, debounced ~800 ms): `updateConversationState(uid, cid, { qaTurns, verdicts })` — no image re-upload.
- **Restore** `openConversation(m)`: `getConversationState`, `keys.clear()`, set `upload/log/result/qaTurns/verdicts` + settings, `setCid(m.id)`, `setLiveSid(null)`, `setView("chat")`, prime `lastSavedRef` so it doesn't re-save. `effKeyUrls` then resolves from Storage `result.key_urls`.
- **Gate on restore**: `askEnabled={!!result?.artifacts && !!liveSid}`; hide/disable "Add key" when `!liveSid` (server session evicted).

### Phase 5 — Sidebar + auth UI → new `frontend/src/components/copilot/components/ConversationSidebar.tsx`
Props `{ conversations, activeCid, collapsed, onToggle, onSelect, onNewChat, saving }`; uses `useAuth()` internally. "New chat" button, collapse toggle, scrollable list (title + relative time, active highlight), footer account block (signed-in → `Avatar` + `DropdownMenu` "Sign out"; signed-out → "Sign in with Google"), "Saving…" indicator. **All needed shadcn primitives already exist** in `frontend/src/components/ui/`: `button`, `avatar`, `dropdown-menu`, `scroll-area`, `separator`, `sheet` (mobile).
- **Integrate**: wrap the existing `<div className="app">` in `<div className="copilot-shell"><ConversationSidebar…/><div className="app">…</div></div>`.
- **Edit `frontend/src/app/copilot/copilot.css`**: add `.copilot-shell { display:flex; height:100%; min-height:0 }`, `.copilot-sidebar` (flex:none; width:260px; collapsed 52px; `border-right:1px solid var(--color-line)`; `background:var(--color-sumi-2)`), `.copilot-shell > .app { flex:1; min-width:0 }`, mobile `position:fixed`. Reuse existing tokens (`--color-sumi-2`, `--color-line`, `--color-ash`, `--color-ao`).

### Phase 6 — Security rules + env (new files at repo root)
- `firestore.rules` + `storage.rules`: `allow read, write: if request.auth != null && request.auth.uid == uid` under `users/{uid}/…`.
- `firebase.json` pointing to both; deploy via `firebase deploy --only firestore:rules,storage` (or paste in console).
- `frontend/.env.example`: the six `NEXT_PUBLIC_FIREBASE_*` keys (empty) + `NEXT_PUBLIC_API_TARGET`.

## 6. Manual Firebase console setup (one-time, cannot be scripted here)
1. **Authentication** → enable the **Google** provider.
2. **Firestore** → create database (production mode).
3. **Storage** → enable the default bucket (must match `NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET`).
4. **Auth → Settings → Authorized domains** → add `localhost`, `127.0.0.1`, `{project}.firebaseapp.com`, `{project}.web.app`, **and the box/prod origin**.

## 7. Risks

- **Authorized domains vs raw IP (biggest blocker):** Firebase Auth rejects bare IP hosts. If the box serves at `100.71.161.102`, `signInWithPopup` fails there — it needs a real hostname, else sign-in only works on localhost / hosted domains. **Confirm the box's prod origin.**
- **1 MB Firestore doc limit:** isolated to `state/main`; a very long session could approach it → fallback is chunking `log` into a subcollection.
- **Video size / free-tier quota:** recon `video.mp4` can be tens of MB; the `includeVideo` flag allows skipping it.
- **Upload-timing race:** server images must be fetched **while the session is still alive** (right after `result`); reloading mid-save loses un-uploaded frames — the `saving` indicator covers this.
- **Static export:** `NEXT_PUBLIC_*` are inlined at build → a Firebase-config change requires a rebuild. `next.config.ts` needs no change (the SDK talks straight to Google, not through the `/session` proxy).

## 8. Verification (end-to-end; `cd frontend && npm run dev`)
1. Signed-out: run a PNG session → still works ephemerally; sidebar shows "Sign in to save".
2. Sign in with Google → avatar appears.
3. Run a keyframe session to completion → sidebar row appears, "Saving…" clears; console shows `users/{uid}/conversations/{cid}` + `state/main` + Storage `keys/`, `mids/`, `montage.png`.
4. **Reload** → still signed in; open from the sidebar → transcript + **frames visible** from Storage (even after the box evicted the session); Ask/Refill disabled (no `liveSid`).
5. Post a Q&A turn / set a verdict on a live session → reload → persisted (debounced save).
6. Run a **video** session → `key_urls` + recon `video.mp4` + per-pair mids restore.
7. "New chat" clears state and starts a new `cid`; the old one stays intact. Sign out → list clears, app still usable.
8. Firestore Rules Playground: a different uid is denied on `users/{uid}/…`.
9. `BUILD_EXPORT=1 npm run build` succeeds; `npx tsc --noEmit` + `npx eslint .` clean.

## 9. Critical files
- **New:** `frontend/src/lib/auth.tsx`, `frontend/src/components/copilot/lib/persistImages.ts`, `frontend/src/components/copilot/components/ConversationSidebar.tsx`, `firestore.rules`, `storage.rules`, `firebase.json`, `frontend/.env.example`
- **Edit:** `frontend/src/lib/firestore.ts`, `frontend/src/lib/firebase.ts`, `frontend/src/models/interfaces.ts`, `frontend/src/components/copilot/CopilotApp.tsx`, `frontend/src/app/layout.tsx`, `frontend/src/app/copilot/copilot.css`

## 10. Follow-ups (docs)
- Add a timestamped note under `Vault/05 - Plans and Roadmap/` and update memory (per CLAUDE.md); fix the stale `ChatSideBar.tsx` mention in `Vault/01 - Architecture/Frontend Web Application.md:112`; ask the user to sync the remote vault.
