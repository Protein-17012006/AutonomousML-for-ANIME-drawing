# Layout Refinement — Stage 3 Backend Plan (Clerk Auth + Firestore/Storage Persistence)

> Status: **proposed** · created 2026-07-08
> Parent: `frontend/docs/plans/layout-refinement-initial-plan.md` (Stage 3)
> Supersedes the auth decision in `frontend/docs/plans/firebase-chat-persistence-plan.md` (auth is now
> **Clerk**, not Firebase Auth; the persistence design from that doc still stands).

## 1. Context

`/copilot` is anonymous and every session is ephemeral (the transcript is *derived* each render by
`deriveMessages(...)` in `frontend/src/components/copilot/lib/chatModel.ts`; a reload wipes it). Stage 3
makes the app **gated + persistent**: users sign in, `/copilot` is protected, and each user's
conversations + frames are saved and reopenable. Stages 1–2 (landing + 5 auth page templates) are done;
this stage wires them to real services and adds persistence.

### Decisions (locked with the user)
- **Auth = Clerk** — via `@clerk/clerk-react` (SPA SDK). NOT `@clerk/nextjs` (its middleware can't run in a
  static export). Chosen because it natively supports the **6-digit email code** (our `/verify-email`) and
  easy Google/GitHub/Apple, and it hosts the user store (no auth DB).
- **Data + files = Firestore + Firebase Storage** — client-direct, per-user security rules, host-agnostic
  (works when served from S3). **All Firebase logic lives in the existing `frontend/src/lib/firebase.ts` +
  `frontend/src/lib/firestore.ts`**, overriding the incomplete stubs; `interfaces.ts` types are replaced.
- **Access gate = HARD** — anonymous users are redirected to `/login` (per the initial plan: "Anonymous
  users must sign in before getting into the Copilot space"). NOTE: conflicts with the Firebase plan's
  "usable signed-out" line; going with the initial plan. Trivial to soften later.

> On "what backend do I write?": with this stack the backend is **managed** (Clerk + Firebase cloud). The
> code you own is (1) a thin **client-side service layer**, (2) **security rules** (the only real
> server-side logic), and (3) console/config. No SQL/DynamoDB/custom server, and — thanks to Clerk — no
> custom email-code service.

## 2. The bridge that makes this stack work: Clerk -> Firebase

Firestore/Storage rules authenticate via `request.auth.uid` from **Firebase Auth**, but users sign in
through **Clerk**. Standard fix (Clerk's Firebase integration): after Clerk sign-in, mint a **Firebase
custom token** via Clerk (`getToken({ template: "integration_firebase" })`) and call
`signInWithCustomToken(auth, token)`. Then `request.auth.uid` == the Clerk user id and per-user rules work.
This reuses the existing `auth` export purely as an **identity bridge** — Clerk stays the only sign-in UI.
Helper lives in `firebase.ts` (e.g. `ensureFirebaseAuth(getToken)`), called once after sign-in.

## 3. Backend services / deliverables

### A. Clerk setup (managed auth — console)
Create a Clerk app -> `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`. Enable: **email/password with email-verification
*code* strategy**, **Google**, **GitHub** (Clerk supplies dev OAuth creds; add your own GitHub OAuth app
for prod). **Apple** needs a paid Apple Developer account -> keep the button, wire last. Enable **password
reset (email code)**. Configure the **Firebase integration** (upload Firebase service account) so Clerk can
mint Firebase custom tokens. Add authorized origins: `localhost` + the S3/prod origin.

### B. Firebase setup (managed data — console)
Firestore (production mode) + Storage bucket (must match `NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET`). Rules keyed
on `request.auth.uid` (= Clerk uid via the bridge).

### C. Auth wiring (client — connect Stage 2 UI to Clerk)
- Install `@clerk/clerk-react`; wrap `frontend/src/app/layout.tsx` children in `<ClerkProvider>` **inside**
  `<ThemeProvider>`.
- Wire the 5 forms with **headless hooks** (keep all existing UI):
  - `LoginForm` -> `useSignIn()` (email/password) + `signIn.authenticateWithRedirect({ strategy: "oauth_*" })` for social.
  - `SignupForm` -> `useSignUp()` -> `prepareEmailAddressVerification({ strategy: "email_code" })` -> route to `/verify-email`.
  - `VerifyEmailForm` -> `useSignUp().attemptEmailAddressVerification({ code })` -> `setActive`.
  - `ForgotPasswordForm` -> `useSignIn().create({ strategy: "reset_password_email_code" })` -> route to `/reset-password`.
  - `ResetPasswordForm` -> `useSignIn().attemptFirstFactor({ strategy: "reset_password_email_code", code, password })`.
  - `SocialAuthButtons` -> `authenticateWithRedirect`.
- **New `/sso-callback`** route (`frontend/src/app/sso-callback/page.tsx`) rendering Clerk's
  `<AuthenticateWithRedirectCallback/>` (OAuth return target).
- **Hard gate on `/copilot`**: in `frontend/src/app/copilot/page.tsx`, use Clerk `useAuth()` — while loading
  show nothing; if `!isSignedIn` `router.replace("/login")`; else render `CopilotApp`. Client-side (static
  export has no middleware).

### D. Data model (`frontend/src/models/interfaces.ts` — override the stale types)
Keep `FirebaseConfig`; delete `Message`/`Chat`/`AIProvider`; add `SessionKind = "png"|"video"|"planted"`,
`ConversationMeta` (light sidebar doc: id, title, kind, engines/fps/stride, sid, uploadLabel, thumb,
createdAt/updatedAt) and `ConversationState` (heavy: `upload: UserTurn|null`, `log: PairEvent[]`,
`result: ResultEvent|null`, `qaTurns: QaTurn[]`, `verdicts`). Reuse copilot types from
`components/copilot/lib/chatModel` + `components/copilot/types`.

### E. Firebase logic in `firebase.ts` + `firestore.ts` (override stub — per instruction)
- **`firebase.ts`**: add `export const storage = getStorage(app);` + `ensureFirebaseAuth(getToken)` bridge helper. Keep `db`/`auth`.
- **`firestore.ts`** (implement all; drop the dead `Message/Chat` imports):
  - Firestore CRUD: `newConversationId(uid)`, `createConversation(uid,cid,meta,state)` (setDoc meta w/
    `serverTimestamp()` + `state/main`), `updateConversationState(uid,cid,patch)`,
    `getConversationState(uid,cid)`, `subscribeConversations(uid,cb): Unsubscribe` (onSnapshot orderBy
    `updatedAt` desc), `deleteConversation(uid,cid)` (best-effort Storage `listAll`+`deleteObject`).
    Coerce `verdicts` keys -> numbers; `serverTimestamp` -> millis (`x?.toMillis?.() ?? null`).
  - Storage persist: `persistSessionImages({ uid, cid, state, keyFiles, includeVideo, onProgress })` — the
    load-bearing **URL rewrite**: upload `keyFiles[i]`->`keys/{i}.png`; fetch+upload every server URL
    (`mid_url`, `annotated_url`, `pair_mids`, `key_urls`, `artifacts.*`), dedupe, rewrite live
    `/session/{sid}/...` URLs -> permanent Storage URLs on the saved copy; **synthesize `result.key_urls`
    for the PNG flow** (else restored key/in-between triptychs render black).
- **Firestore layout**: `users/{uid}/conversations/{cid}` (meta) + `.../state/main` (state, loaded on open).
  **Storage layout**: `users/{uid}/conversations/{cid}/{keys,mids,annotated,pair_mids}/...png`, `montage.png`,
  `video.mp4`, `report.<ext>`.

### F. Co-pilot wiring (`frontend/src/components/copilot/CopilotApp.tsx`)
- New state: Clerk `user`/uid, `cid`, **`liveSid`**, `conversations`, `saving`, `lastSavedRef`.
- **Introduce `liveSid`** (there is none today — `onResult` at `CopilotApp.tsx:143-144` only `setResult(r)`):
  set `liveSid = r.artifacts?.montage.split("/")[2] ?? null` in `onResult`, and **rewrite `refillKey`
  (`:213-216`) + `onAsk` (`:276-277`) to use `liveSid`** instead of re-parsing the artifact URL (post-restore
  those are Storage URLs -> the split breaks). `clearAll()` (`:98-107`) also nulls `cid` + `liveSid`.
- After sign-in: `ensureFirebaseAuth(getToken)` then `subscribeConversations(uid, setConversations)`.
- **Save on run-complete** (effect on `[result, running, user]`, deduped by `result.artifacts.montage` via
  `lastSavedRef`): `persistSessionImages(...)` -> `createConversation`/`updateConversationState`; toggle `saving`.
- **Light save** (effect on `[qaTurns, verdicts, cid]`, debounced ~800ms): `updateConversationState` (no re-upload).
- **Restore `openConversation(m)`**: `getConversationState`, `keys.clear()`, set
  `upload/log/result/qaTurns/verdicts` + settings, `setCid`, `setLiveSid(null)`, prime `lastSavedRef` (no
  re-save). `effKeyUrls` (`:88-94`) then resolves frames from Storage `result.key_urls`.
- **Gate** ask/refill on `!!liveSid` (server session evicted after restore).

### G. History sidebar + account (EXTEND `frontend/src/components/common/AppSidebar.tsx`)
AppSidebar already has the seams: a static `History` group driven by a `SESSIONS` array (`:32-38`,
`:118-130`) and a static account footer (`:133-150`). Extend it (don't add a new sidebar):
- Replace `SESSIONS` with live `conversations` (props from CopilotApp) + active-cid highlight + `onSelect` +
  a **"New chat"** button (net-new) + a "Saving..." indicator.
- Replace the placeholder footer ("Animator"/"Free") with Clerk `useUser()` avatar + name + a sign-out
  `DropdownMenu` (`useClerk().signOut()`).
- Pass `{ conversations, activeCid, onSelect, onNewChat, saving }` as props (AppSidebar takes none today).

### H. Security rules + env (new files at repo root)
- `firestore.rules` + `storage.rules`: `allow read, write: if request.auth != null && request.auth.uid == uid`
  under `users/{uid}/...`. `firebase.json` referencing both.
- `frontend/.env.example`: 6 `NEXT_PUBLIC_FIREBASE_*` + `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` + `NEXT_PUBLIC_API_TARGET`.

### I. S3 / cross-origin prerequisite
If the frontend moves to **S3** while the co-pilot API stays on the box, add **CORS** to the FastAPI
`/session*` responses for the S3 origin — `persistSessionImages` does `fetch()` on server frames, which
becomes cross-origin. Clerk + Firebase SDKs are host-agnostic. Static export inlines `NEXT_PUBLIC_*` at
build -> any Clerk/Firebase config change needs a rebuild. (Optional hardening, later: verify the Clerk JWT
on FastAPI so only signed-in users can run the pipeline server-side.)

## 4. Suggested phasing
1. Clerk provider + wire 5 forms + `/sso-callback` + `/copilot` guard -> **auth works end-to-end**.
2. `firebase.ts` storage export + `ensureFirebaseAuth` bridge + `interfaces.ts` types.
3. `firestore.ts` CRUD + `persistSessionImages`.
4. `CopilotApp.tsx` wiring (`liveSid`, subscribe, save, light-save, restore, gates).
5. `AppSidebar.tsx` live history + Clerk account footer + "New chat".
6. Rules + env + CORS, then full verification.

## 5. Critical files
- **New:** `frontend/src/app/sso-callback/page.tsx`, `firestore.rules`, `storage.rules`, `firebase.json`, `frontend/.env.example`.
- **Edit:** `frontend/src/lib/firebase.ts`, `frontend/src/lib/firestore.ts`, `frontend/src/models/interfaces.ts`,
  `frontend/src/components/copilot/CopilotApp.tsx`, `frontend/src/components/common/AppSidebar.tsx`,
  `frontend/src/app/layout.tsx`, `frontend/src/app/copilot/page.tsx`, and the 5 `components/auth/*Form.tsx`.
- **New dep:** `@clerk/clerk-react`.

## 6. Verification (end-to-end; `cd frontend && npm run dev`)
1. Sign up with email -> `/verify-email` 6-digit code -> verified + signed in.
2. Google / GitHub -> `/sso-callback` -> signed in. Visit `/copilot` signed-out -> redirected to `/login`.
3. Run a keyframe session -> sidebar row appears, "Saving..." clears; Firestore shows
   `users/{uid}/conversations/{cid}` + `state/main`; Storage shows `keys/`, `mids/`, `montage.png`.
4. **Reload** -> still signed in; open from sidebar -> transcript + **frames visible from Storage**;
   Ask/Refill disabled (no `liveSid`).
5. Post a Q&A / set a verdict -> reload -> persisted (debounced save).
6. Video session -> `key_urls` + `video.mp4` + per-pair mids restore.
7. "New chat" starts a fresh `cid`; old one intact. Sign out -> list clears.
8. Firestore Rules Playground: a different uid is denied under `users/{uid}/...`.
9. `BUILD_EXPORT=1 npm run build` succeeds; `npx tsc --noEmit` + `npx eslint .` clean.

## 7. Follow-ups
Add a timestamped note under `Vault/05 - Plans and Roadmap/` + update memory (CLAUDE.md); reconcile the
Firebase-plan doc (auth is now Clerk; access gate is hard); ask the user to sync the remote vault. Confirm
the box's **prod origin / S3 domain** for Clerk + Firebase authorized domains.
