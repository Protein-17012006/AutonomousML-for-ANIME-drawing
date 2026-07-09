# Layout Refinement — Stage 3 Backend Plan (Cognito Auth + DynamoDB/S3 Persistence)

> Status: **proposed** · created 2026-07-08 · **rewritten 2026-07-09** (stack changed to AWS-native)
> Parent: `frontend/docs/plans/layout-refinement-initial-plan.md` (Stage 3)
> Supersedes the auth **and** persistence decisions in earlier drafts: auth is now **Amazon Cognito**
> (not Clerk / not Firebase Auth), and persistence is **DynamoDB + S3** (not Firestore / Firebase
> Storage). The `firebase-chat-persistence-plan.md` doc is superseded wholesale by this one.

## 1. Context

`/copilot` is anonymous and every session is ephemeral (the transcript is *derived* each render by
`deriveMessages(...)` in `frontend/src/components/copilot/lib/chatModel.ts`; a reload wipes it). Stage 3
makes the app **gated + persistent**: users sign in, `/copilot` is protected, and each user's
conversations + frames are saved and reopenable. Stages 1–2 (landing + 5 auth page templates) are done;
this stage wires them to real services and adds persistence — **on AWS**, the platform the project
already deploys to.

**The AWS estate already exists and is centrally owned.** Per the deploy runbook
(`frontend/docs/deploy/aws-s3-deploy-guide-vi.pdf`): the frontend is a **static export** (`out/`) synced
to `s3://copilot-g4-cos30018-deploy/frontend/`, pulled by an **EC2 nginx** box via SSM, and served
through **CloudFront** (`EYFLJZ36A9EN5`) at **https://inbetween-copilot.click**. Account
`834996123571`, region `ap-southeast-1`. `/session*` is reverse-proxied **same-origin** by nginx to the
GPU box. Auth/data infra lives as **CloudFormation/CDK stacks (`infra/` in the main repo)** managed by
**R0 (Hoàng) / R3 (Long)**: a **Cognito** pool already gates the site, and `copilot-*` stacks own
data/auth/frontdoor/cdn. The existing DynamoDB `copilot_sessions` table and `s3://…-artifacts` bucket
hold real-run report evidence and are **off-limits** — this stage adds **new** resources, coordinated
with R0/R3, and never touches those.

### Decisions (locked with the user)
- **Auth = Amazon Cognito, reusing the existing site User Pool** — via **AWS Amplify v6 (`aws-amplify`)
  Auth** headless APIs. Amplify's functions are called from our existing Stage-2 form UI (kept as-is);
  no Cognito Hosted UI for email/password. Cognito natively supports the **6-digit email code**
  (our `/verify-email`) and password-reset-by-code. Requires **R0** to enable self-service sign-up +
  email-code + a Hosted UI domain + the Google IdP + an app client whose callback URLs include our SPA.
- **Data + files = DynamoDB + S3, accessed client-direct via a Cognito Identity Pool.** Amplify
  federates the User-Pool JWT into a Cognito **Identity Pool** which vends **temporary AWS credentials**
  (`fetchAuthSession()`); the browser calls DynamoDB and S3 directly. **IAM policies are the per-user
  access rules** — the AWS analog of Firestore security rules. No SQL, no custom server tier.
- **Access gate = HARD** — anonymous users are redirected to `/login` (per the initial plan: "Anonymous
  users must sign in before getting into the Copilot space"). Client-side (static export = no middleware).
- **Social = Google only this stage.** Google is wired via `signInWithRedirect` (native Cognito IdP).
  The **GitHub + Apple buttons stay visible but disabled ("coming soon")** — GitHub needs a custom OIDC
  provider (it isn't OIDC-compliant) and Apple needs a paid Apple Developer account; both revisited later.
- **Remove Firebase entirely** — the `firebase` dependency, `lib/firebase.ts`, the empty `lib/firestore.ts`
  stub, and the `FirebaseConfig`/`Message`/`Chat` types all go.

> On "what backend do I write?": with this stack the backend is **managed** (Cognito + DynamoDB + S3).
> The code you own is (1) a thin **client-side service layer** (Amplify + AWS SDK calls), and (2) the
> UI wiring. The only real "server-side logic" is the **IAM policy** on the Identity Pool role, which
> lives in `infra/` and is authored by R0/R3. No Lambda, no API Gateway, no custom email service.

## 2. How this stack works: Cognito User Pool + Identity Pool

Unlike the Clerk→Firebase design, **there is no token-minting bridge** — AWS federates natively:

1. The user signs in through our forms → Amplify authenticates against the **Cognito User Pool** and
   holds the session (ID/access tokens).
2. `fetchAuthSession()` exchanges that User-Pool token at the **Cognito Identity Pool** for **temporary
   AWS credentials** bound to the pool's *authenticated* IAM role.
3. The browser uses those credentials to call **DynamoDB** and **S3** directly. The IAM role's policy
   restricts every call to the caller's own data via the identity variable
   `${cognito-identity.amazonaws.com:sub}` (the per-user `identityId`).

So the same `identityId` is the DynamoDB partition key **and** the S3 prefix — one consistent per-user
key, enforced by IAM. Configure everything once with `Amplify.configure({ Auth: { Cognito: {
userPoolId, userPoolClientId, identityPoolId, loginWith: { oauth: {...}, email: true } } } })`.

### 2b. How auth reaches the data at runtime (and what "session" means)

Two Cognito pieces, two jobs: the **User Pool** proves *who you are* (sign-up/in, email code, Google)
and issues **JWTs**; the **Identity Pool** trades a JWT for **temporary AWS IAM credentials** so the
browser can call AWS directly.

```
                 (1) signIn(email,pw)                (2) fetchAuthSession()
   /login   ─────────────────────────▶  Cognito  ───────────────────────▶  Cognito
  (Amplify) ◀──────  JWT tokens  ─────  USER POOL      JWT sent to          IDENTITY POOL
     │                                                                           │
     │                                          temp AWS creds + identityId ◀────┘
     │  (3) browser calls AWS directly, SigV4-signed with those temp creds:
     ▼                                                     ▼
  DynamoDB  copilot_chats  (chat metadata)          S3  …-userdata  (state.json + frames)
  IAM: LeadingKeys = your identityId                IAM: prefix private/{identityId}/*
```

1. **Sign in** → Amplify `signIn()` (or `signInWithRedirect` for Google) authenticates against the
   **User Pool**, which returns JWTs that Amplify stores + auto-refreshes.
2. **Get creds** → `fetchAuthSession()` sends the User-Pool token to the **Identity Pool**, which
   assumes the authenticated IAM role and returns **temp AWS credentials** + a stable `identityId`.
3. **Read/write chats** → with those creds the browser calls **DynamoDB** (`copilot_chats` metadata) and
   **S3** (`…-userdata` `state.json` + frames) directly; the role's IAM policy scopes every call to the
   caller's own `identityId`, so no user can ever touch another's data even though there's no server.
4. **On reload** → Amplify restores/refreshes the session from stored tokens; the `/copilot` guard
   checks `getCurrentUser()`; if valid it re-fetches `listConversations()`. No re-login until the
   refresh token expires.

**"Session" means two different things — Cognito only gates one:**
- **Saved chat (`cid`)** — the persisted per-user record in DynamoDB + S3. **This is what Cognito
  protects** (the flow above).
- **Live pipeline session (`sid`)** — an ephemeral run on the GPU box (`/session/{sid}/…`, FastAPI).
  This path is currently **unauthenticated** (nginx proxies it same-origin); Cognito is not in front of
  it. (Optional future hardening — verify the Cognito JWT on FastAPI — is out of scope for Stage 3.)

**The ALB gate is a separate, third thing.** If `inbetween-copilot.click` is gated at the **ALB**
(`authenticate-cognito`), that guards *viewing the site at all* at the edge (Cognito Hosted UI) — it is
**not** what grants data access; the app still needs its own Amplify session (steps 1–2) for AWS creds.
If that edge gate is on it would bypass our in-app `/login`, so §7 asks R0 to remove/scope it.

## 3. Backend services / deliverables

### A. Cognito setup (managed auth — R0, on the EXISTING pool)
Reuse the User Pool that already gates the site. R0 configures: **self-service sign-up** + **email
verification by code**, **password reset by code**, a **Hosted UI domain**, the **Google** IdP
(needs a free Google OAuth client), and an **app client** whose allowed callback/redirect URLs include
`http://localhost:3000/sso-callback` and `https://inbetween-copilot.click/sso-callback`. Export
`userPoolId`, `userPoolClientId`, and Hosted-UI `domain` for the frontend env. (GitHub/Apple IdPs
deferred.)

### B. Identity Pool + data resources (managed data — R0/R3, in `infra/`)
A **Cognito Identity Pool** linked to the User Pool, with an **authenticated IAM role**. A **new**
DynamoDB table **`copilot_chats`** (on-demand) and a **new** S3 bucket
**`copilot-g4-cos30018-userdata`** (with a CORS config, §I). The authenticated role's policy scopes
DynamoDB to `dynamodb:LeadingKeys = ${cognito-identity.amazonaws.com:sub}` on `copilot_chats` and S3 to
`private/${cognito-identity.amazonaws.com:sub}/*` on the userdata bucket. **Do not reuse the forbidden
`copilot_sessions` / `…-artifacts`.**

### C. Auth wiring (client — connect Stage 2 UI to Cognito via Amplify)
- Install `aws-amplify` (v6). Add a small client boot component that calls `Amplify.configure(...)` and
  wrap it in `frontend/src/app/layout.tsx` inside `<body>` (around/with the existing `ThemeProvider`).
- Wire the forms with Amplify headless calls (**keep all existing UI**; forms currently use uncontrolled
  `name=` inputs → read via `FormData` or add controlled state):
  - `LoginForm` → `signIn({ username: email, password })`; handle `nextStep` (e.g. `CONFIRM_SIGN_UP` → `/verify-email`).
  - `SignupForm` → `signUp({ username: email, password, options: { userAttributes: { email } } })` → route to `/verify-email`.
  - `VerifyEmailForm` → `confirmSignUp({ username: email, confirmationCode })` → `autoSignIn()` → `/copilot`.
  - `ForgotPasswordForm` → `resetPassword({ username: email })` → route to `/reset-password`.
  - `ResetPasswordForm` → `confirmResetPassword({ username: email, confirmationCode, newPassword })` → `/login`.
  - `SocialAuthButtons` → **wire Google only**: `signInWithRedirect({ provider: "Google" })`. Render the
    **GitHub + Apple buttons disabled** with a "coming soon" affordance (keep the markup, don't wire).
    Social is a **full-page redirect** through Cognito's hosted domain that returns to `/sso-callback`.
- Carry the pending **email/username** across the signup→verify and forgot→reset route hops
  (`sessionStorage` or a small context) — Cognito flows are username-centric.
- **New `/sso-callback`** route (`frontend/src/app/sso-callback/page.tsx`): Amplify completes the OAuth
  code exchange on load (`Hub.listen("auth", …)` / `getCurrentUser()`); show a spinner, then route to `/copilot`.
- **Hard gate on `/copilot`**: `frontend/src/app/copilot/page.tsx` is currently unguarded (it just
  dynamic-imports `CopilotApp`). On mount call `getCurrentUser()` / `fetchAuthSession()`; while loading
  render nothing; if not signed in `router.replace("/login")`; else render `CopilotApp`.

### D. Data model (`frontend/src/models/interfaces.ts` — replace the stale types)
Delete `FirebaseConfig`/`Message`/`Chat`/`AIProvider`. Add `SessionKind = "png"|"video"|"planted"`,
`ConversationMeta` (light sidebar doc: id, title, kind, engines/fps/stride, sid, uploadLabel, thumb,
createdAt/updatedAt) and `ConversationState` (heavy: `upload: UserTurn|null`, `log: PairEvent[]`,
`result: ResultEvent|null`, `qaTurns: QaTurn[]`, `verdicts`). Reuse copilot types from
`components/copilot/lib/chatModel` + `components/copilot/types`.

### E. AWS service layer (replace the Firebase files)
- **`frontend/src/lib/amplify.ts`** (replaces `firebase.ts`): `Amplify.configure(...)` + helpers
  `getIdentityId()`, `getDynamoDoc()` (a `@aws-sdk/lib-dynamodb` `DynamoDBDocumentClient` built from
  `fetchAuthSession()` credentials), and small Storage helpers (upload + a `getUrl()` wrapper that signs
  stored S3 keys to short-lived URLs on read).
- **`frontend/src/lib/chatStore.ts`** (replaces the empty `firestore.ts`):
  - **DynamoDB CRUD** on `copilot_chats`: `newConversationId()`, `createConversation(cid, meta)`,
    `updateConversationMeta(cid, patch)`, `listConversations(): ConversationMeta[]`
    (`Query` `pk = identityId`, **client-sort by `updatedAt` desc**), `deleteConversation(cid)`.
  - **S3 (Amplify Storage, `private` access level = per-identity prefix)**:
    `putConversationState(cid, state)` → `state.json`; `getConversationState(cid)`; and the load-bearing
    `persistSessionImages({ cid, state, keyFiles, includeVideo, onProgress })` — upload `keyFiles[i]` →
    `keys/{i}.png`; fetch + upload every ephemeral server URL (`mid_url`, `annotated_url`, `pair_mids`,
    `key_urls`, `artifacts.*`), dedupe, **rewrite the live `/session/{sid}/...` URLs → stable S3 keys on
    the saved copy** (userdata bucket is private → the app signs a short-lived URL via Amplify `getUrl()`
    at render, so persist keys, not URLs), and **synthesize `result.key_urls` for the PNG flow** (else
    restored key/in-between triptychs render black).
- **No real-time subscription**: DynamoDB has no `onSnapshot`. The old `subscribeConversations` becomes
  a one-shot `listConversations()` that is **re-fetched after each save/delete** (an explicit change
  from the Firestore design — the sidebar updates on mutation, not via a live stream).

### F. Co-pilot wiring (`frontend/src/components/copilot/CopilotApp.tsx`)
- New state: Cognito `user`/`identityId`, `cid`, **`liveSid`**, `conversations`, `saving`, `lastSavedRef`.
- **Introduce `liveSid`** (there is none today — `onResult` only `setResult(r)`): set
  `liveSid = r.artifacts?.montage.split("/")[2] ?? null` in `onResult` (in both `run` and `runVideo`),
  and **rewrite `refillKey` + `onAsk` to use `liveSid`** instead of re-parsing the artifact URL
  (post-restore those are S3 URLs → the split breaks). `clearAll()` also nulls `cid` + `liveSid`.
  *(Line refs: `effKeyUrls` ~L84-90, `clearAll` ~L94-103, `onResult` ~L140/L167, `refillKey` tail
  ~L213-214, `onAsk` ~L245-272 — verify at edit time.)*
- After sign-in: resolve `identityId` → `listConversations()` → `setConversations`; refetch after saves.
- **Save on run-complete** (effect on `[result, running, user]`, deduped by `result.artifacts.montage`
  via `lastSavedRef`): `persistSessionImages(...)` → `putConversationState` +
  `createConversation`/`updateConversationMeta`; toggle `saving`.
- **Light save** (effect on `[qaTurns, verdicts, cid]`, debounced ~800ms): `putConversationState` +
  `updateConversationMeta(updatedAt)` (no re-upload), then refetch the list.
- **Restore `openConversation(m)`**: `getConversationState`, `keys.clear()`, set
  `upload/log/result/qaTurns/verdicts` + settings, `setCid`, `setLiveSid(null)`, prime `lastSavedRef`
  (no re-save). `effKeyUrls` then resolves frames from the persisted S3 keys in `result.key_urls`
  (signed to URLs via `getUrl()` on read).
- **Gate** ask/refill on `!!liveSid` (server session evicted after restore).

### G. History sidebar + account (EXTEND `frontend/src/components/common/AppSidebar.tsx`)
AppSidebar is static and takes no props today (`SESSIONS` array, a History group, and a placeholder
account footer). Extend it (don't add a new sidebar):
- Replace `SESSIONS` with live `conversations` (props from CopilotApp) + active-cid highlight +
  `onSelect` + a **"New chat"** button + a "Saving…" indicator.
- Replace the placeholder footer ("Animator"/"Free") with the Cognito user's avatar + name (from
  `getCurrentUser()` / user attributes) + a sign-out `DropdownMenu` (`signOut()` from `aws-amplify/auth`).
- Pass `{ conversations, activeCid, onSelect, onNewChat, saving }` as props (AppSidebar takes none today).

### H. IAM policy + env
- **IAM (in `infra/`, R0/R3)** — the authenticated Identity-Pool role: DynamoDB with
  `dynamodb:LeadingKeys = ${cognito-identity.amazonaws.com:sub}` on `copilot_chats`, and S3 with prefix
  `private/${cognito-identity.amazonaws.com:sub}/*` on `copilot-g4-cos30018-userdata`. These IAM
  conditions replace `firestore.rules` / `storage.rules`.
- **`frontend/.env.example`**: `NEXT_PUBLIC_AWS_REGION=ap-southeast-1`,
  `NEXT_PUBLIC_COGNITO_USER_POOL_ID`, `NEXT_PUBLIC_COGNITO_USER_POOL_CLIENT_ID`,
  `NEXT_PUBLIC_COGNITO_IDENTITY_POOL_ID`, `NEXT_PUBLIC_COGNITO_DOMAIN`, `NEXT_PUBLIC_CHATS_TABLE`,
  `NEXT_PUBLIC_USERDATA_BUCKET`, `NEXT_PUBLIC_API_TARGET`. Static export **inlines `NEXT_PUBLIC_*` at
  build** → any Cognito/AWS config change needs a rebuild + redeploy.

### I. Cross-origin + deploy
- **No FastAPI CORS needed**: the deployed site serves `/session*` **same-origin** via the nginx
  reverse-proxy (dev proxies it too), so `persistSessionImages`' `fetch()` on box frames is same-origin.
  *(This corrects the earlier Clerk/Firebase draft, which called for FastAPI CORS.)*
- **S3 bucket CORS (new)**: `copilot-g4-cos30018-userdata` needs a CORS config allowing
  `https://inbetween-copilot.click` + `http://localhost:3000`, because Amplify Storage hits the S3 REST
  endpoint cross-origin. (infra/R0/R3.)
- **Deploy** exactly per the runbook: `BUILD_EXPORT=1 npm run build` → `aws s3 sync out/
  s3://copilot-g4-cos30018-deploy/frontend/ --delete` → SSM `refresh-frontend.sh` → optional CloudFront
  invalidation (there's a `deploy-frontend.ps1`).

## 4. Chat-history schema (DynamoDB index + S3 payload)

A "chat" = one co-pilot session. **DynamoDB holds only lightweight, queryable metadata** (one small
item per chat, for the sidebar); **S3 holds the heavy `state.json` + all binary frames**. Rationale:
DynamoDB's **400 KB item cap** can't hold the log+result+QA payload, frames are binary (S3 anyway), and
S3-only listing is slow/unsorted — so the index (DynamoDB) is split from the payload (S3).

**DynamoDB `copilot_chats`** (on-demand / PAY_PER_REQUEST):

| Key / attr | Type | Notes |
| --- | --- | --- |
| `identityId` **(PK)** | S | Cognito Identity Pool id — the per-user partition IAM `LeadingKeys` locks |
| `CONV#{cid}` **(SK)** | S | direct Get/Update/Delete by chat; `CONV#` prefix reserves room for future item types |
| `title` | S | e.g. "Genga pair 03 · walk cycle" |
| `kind` | S | `png` \| `video` \| `planted` |
| `engines`,`fps`,`stride` | S/N | run settings, for the sidebar chips |
| `sid` | S | original live session id (reference; may be evicted) |
| `uploadLabel`,`thumb` | S | label + **S3 key** of the montage (signed on read, not a stored URL) |
| `createdAt`,`updatedAt` | N | epoch millis |
| `schemaVersion` | N | forward-migration guard |

**Access patterns:** (1) sidebar list = `Query(PK = identityId)` + **client-sort by `updatedAt` desc**
(add a `byUpdatedAt` GSI only if lists grow large); (2) open a chat = read the **deterministic** S3 key
(no pointer lookup needed); (3) create = `PutItem` + `putObject(state.json)` + upload frames; (4) light
save = overwrite `state.json` + `UpdateItem(updatedAt)`; (5) delete = `DeleteItem` + delete the S3 prefix.

**S3 payload** (Amplify Storage `private` level → auto-prefixed `private/{identityId}/`):

```
private/{identityId}/conversations/{cid}/
  state.json            # the heavy ConversationState (below)
  keys/*.png            # uploaded key drawings
  mids/*  annotated/*  pair_mids/*    # generated / QA'd / per-pair frames
  montage.png           # result montage (also the thumb)
  video.mp4             # video-input source (video flow only)
  report.<ext>          # exported report
```

`state.json` = `{ schemaVersion, upload: UserTurn, log: PairEvent[], result: ResultEvent,
qaTurns: QaTurn[], verdicts: Record<frameIdx, "accept"|"reject"> }`.

**Two design points:** (a) we store the **source state, not rendered messages** — the chat bubbles are
derived at render by the existing `deriveMessages(...)`, so persisting `upload/log/result/qaTurns/verdicts`
reconstructs the whole chat; (b) `persistSessionImages` **rewrites the ephemeral `/session/{sid}/...`
URLs → stable S3 keys** inside the saved `state.json` and synthesizes `result.key_urls` for the PNG
flow — the userdata bucket is private, so keys are persisted and signed to short-lived URLs via Amplify
`getUrl()` on read (not baked permanent URLs), which lets a reopened chat render its frames even when
the box is offline.

**Isolation is schema-level:** DynamoDB `LeadingKeys = ${cognito-identity.amazonaws.com:sub}` and the S3
prefix `private/${…:sub}/*` both key on the same `identityId`, so the browser can only ever touch its
own partition + prefix even though it calls AWS directly.

## 5. Suggested phasing
1. `Amplify.configure` + wire the 5 forms + `/sso-callback` + `/copilot` guard → **auth end-to-end**
   (needs R0 to enable self-signup + email-code + Hosted UI + Google on the existing pool).
2. `lib/amplify.ts` (Identity-Pool creds + Dynamo doc client) + `interfaces.ts` types.
3. `lib/chatStore.ts` — DynamoDB CRUD + S3 state + `persistSessionImages` (needs `copilot_chats` +
   `…-userdata` bucket + IAM from R0/R3).
4. `CopilotApp.tsx` wiring (`liveSid`, list+refetch, save, light-save, restore, gates).
5. `AppSidebar.tsx` live history + Cognito account footer + "New chat".
6. IAM + bucket CORS + env, then full verification and deploy.

## 6. Critical files
- **New (frontend):** `frontend/src/app/sso-callback/page.tsx`, `frontend/src/lib/amplify.ts`,
  `frontend/src/lib/chatStore.ts`, `frontend/.env.example`.
- **New (infra, main repo — R0/R3):** Cognito Identity Pool + authenticated IAM role, `copilot_chats`
  table, `copilot-g4-cos30018-userdata` bucket + CORS, plus the existing-pool config.
- **Edit:** `frontend/src/models/interfaces.ts`, `frontend/src/components/copilot/CopilotApp.tsx`,
  `frontend/src/components/common/AppSidebar.tsx`, `frontend/src/app/layout.tsx`,
  `frontend/src/app/copilot/page.tsx`, and the 5 `components/auth/*Form.tsx` + `SocialAuthButtons.tsx`.
- **Remove:** the `firebase` dependency, `frontend/src/lib/firebase.ts`, `frontend/src/lib/firestore.ts`.
- **New deps:** `aws-amplify` (v6 — Auth + Storage), `@aws-sdk/client-dynamodb`, `@aws-sdk/lib-dynamodb`.

## 7. Open items (confirm with R0 before building)
- **ALB gate vs in-app login** (decided: in-app pages drive login everywhere): confirm whether
  `inbetween-copilot.click` is currently **ALB (authenticate-cognito)** gated. If yes, **R0 removes that
  gate** so the SPA's `/login` + `/signup` are what users actually see (else Cognito's hosted login
  bypasses them on the deployed URL).
- **Existing pool must allow self-service sign-up + email-code** (it currently holds only hand-issued
  team users: `hoang/long/khang/...`).
- **Google IdP + Hosted UI domain + app-client callback URLs** (`localhost:3000/sso-callback` +
  `inbetween-copilot.click/sso-callback`) configured on the existing pool by R0.
- **GitHub + Apple deferred** — buttons ship disabled. GitHub = custom OIDC provider + shim (not
  OIDC-compliant); Apple = paid Apple Developer account.

## 8. Verification (end-to-end; `cd frontend && npm run dev`)
1. Sign up with email → `/verify-email` 6-digit code → verified + signed in.
2. Google → `/sso-callback` → signed in. Visit `/copilot` signed-out → redirected to `/login`.
3. Run a keyframe session → sidebar row appears, "Saving…" clears; DynamoDB `copilot_chats` shows the
   item; S3 shows `state.json` + `keys/` + `montage.png` under `private/{identityId}/conversations/{cid}/`.
4. **Reload** → still signed in; open from sidebar → transcript + **frames visible from S3**; Ask/Refill
   disabled (no `liveSid`).
5. Post a Q&A / set a verdict → reload → persisted (debounced light save).
6. Video session → `key_urls` + `video.mp4` + per-pair mids restore.
7. "New chat" starts a fresh `cid`; old one intact. Sign out → list clears.
8. IAM isolation: a second identity cannot read another's `copilot_chats` items or S3 prefix.
9. `BUILD_EXPORT=1 npm run build` succeeds; `npx tsc --noEmit` + `npx eslint .` clean; then `s3 sync` +
   SSM refresh → verify live on `inbetween-copilot.click`.

## 9. Follow-ups
Add a timestamped note under `Vault/05 - Plans and Roadmap/` + update memory (CLAUDE.md still says
"Firebase wired — off the session path"; reconcile it). **File the AWS infra ask with R0/R3** (existing-
pool config + Identity Pool + `copilot_chats` + `copilot-g4-cos30018-userdata` bucket + IAM + bucket
CORS). Ask the user to sync the remote vault.
