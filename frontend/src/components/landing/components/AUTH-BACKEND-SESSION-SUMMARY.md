# Authentication and Backend Service Handoff

Last updated: 2026-07-18 (Asia/Saigon)

This note summarizes the authentication, Cognito, Google OAuth, FastAPI, and local-testing work completed in the current implementation session. It is intended to let another teammate continue without reconstructing the design from the working tree or chat history.

## Current outcome

Phase 1 now uses a stateless Cognito ID-token cookie boundary:

```text
Cognito password or Google sign-in
    -> Amplify temporarily receives the Cognito ID token
    -> browser sends it once as Bearer to POST /auth/session
    -> FastAPI verifies Cognito signature, issuer, audience, expiry, and token_use=id
    -> FastAPI sets an HttpOnly SameSite=Lax cookie
    -> browser sends the cookie on same-origin API requests
    -> FastAPI revalidates the ID token and derives the authoritative Cognito sub
```

There is no opaque-token database, DynamoDB session table, ID-token secret per user, or custom KMS key. The signed Cognito ID token is held in the server-issued cookie. The cookie expires with the ID token; Phase 1 deliberately has no application refresh-token flow, so expiry requires another login.

The browser no longer receives AWS Identity Pool credentials and no longer accesses private DynamoDB or S3 resources directly. FastAPI is the authentication and authorization boundary.

## AWS resources and current state

Region: `ap-southeast-1`

| Resource | Identifier | Purpose | Current state |
| --- | --- | --- | --- |
| Cognito User Pool | `ap-southeast-1_VSo6hlI6k` / `copilot-users` | Shared user directory | Self-signup enabled; email auto-verification enabled; existing users preserved |
| Public SPA client | `5dbs2g7vahmp3tl2ccs280ofsn` / `copilot-spa` | Next.js password login, signup, Google OAuth code/PKCE | No client secret; supports `COGNITO` and `Google` |
| Legacy ALB client | `1firr76aptpp2hu8vg4ai89ub9` / `copilot-alb` | Existing ALB `authenticate-cognito` action | Confidential client with secret; retained because production ALB still references it |
| Cognito domain | `copilot-g4-cos30018-auth.auth.ap-southeast-1.amazoncognito.com` | Hosted authorization/logout endpoints | Active |
| Google credentials secret | `/copilot/google-oauth` | Cognito-to-Google client ID/secret | Real credentials populated; secret value must never enter source control or chat |
| Google IdP | `Google` | Federated Google authentication in the User Pool | Enabled through CloudFormation |

CloudFormation stack `copilot-auth` is `UPDATE_COMPLETE`. The deployed public-client callbacks are:

```text
http://localhost:3000/sso-callback
https://inbetween-copilot.click/sso-callback
```

Logout URLs are:

```text
http://localhost:3000/login
https://inbetween-copilot.click/login
```

The Google web client must use Cognito—not localhost—as its Google redirect:

```text
Authorized JavaScript origin:
https://copilot-g4-cos30018-auth.auth.ap-southeast-1.amazoncognito.com

Authorized redirect URI:
https://copilot-g4-cos30018-auth.auth.ap-southeast-1.amazoncognito.com/oauth2/idpresponse
```

## Why there are two Cognito app clients

The clients do not call each other. They are two applications registered against the same User Pool:

```text
Local/new application path:
browser -> copilot-spa -> FastAPI /auth/session -> application cookie

Current production compatibility path:
browser -> ALB -> copilot-alb -> ALB session cookie -> application
```

`copilot-spa` is the long-term browser client. `copilot-alb` is a transition client and must not be deleted yet. Removing it while the ALB listener still uses `authenticate-cognito` would break the production front door.

Google is enabled on `copilot-spa`, not the legacy ALB client. Complete production Google authentication therefore waits for the production ALB gate removal. Retire `copilot-alb` only after all of the following are true:

1. the backend box is available;
2. `/auth/*` is routed to the production FastAPI service;
3. secure FastAPI cookie auth is tested through the real HTTPS domain;
4. the ALB `authenticate-cognito` action is removed from `infra/20-frontdoor.yaml` and AWS;
5. the CloudFormation and deployed AWS state are confirmed in sync.

## Backend implementation

### `service/core/auth.py`

- Added strict Cognito User Pool ID-token validation through `PyJWT[crypto]` and Cognito JWKS.
- Requires the expected issuer, SPA client audience, expiry, `sub`, and `token_use=id`.
- Accepts a Bearer token only at the cookie-bootstrap boundary.
- Revalidates the cookie on every protected request.
- Uses Cognito `sub` as the authoritative owner identity.
- Retains separately verified, explicitly enabled ALB OIDC claims for the transition period.
- If cookie and ALB identities are both present, their `sub` values must agree.
- Enforces same-origin checks on cookie-authenticated state-changing requests.
- Enforces per-session ownership without revealing whether another user's session exists; unauthorized access receives the same 404 detail as an unknown session.

Cookie names:

```text
Production secure cookie: __Host-copilot_id
Local HTTP cookie:        copilot_id
```

### `service/auth_api.py`

Added:

```text
POST /auth/session  Validate one Bearer ID token and set the cookie
GET  /auth/me       Return user_sub, username, and token expiry
POST /auth/logout   Enforce same-origin request and delete the cookie
```

The cookie is `HttpOnly`, `SameSite=Lax`, path `/`, and secure in production. Its maximum age and expiry match the Cognito ID token.

### `service/app.py`

- Registers the authentication router before the application routers.
- Protects `/session`, `/session/*`, `/demo`, and `/demo/*` when authentication is enabled or an auth identity is presented.
- Deletes an invalid cookie after a 401 response.
- Applies the same Cognito-`sub` ownership boundary to all `/session/{sid}/*` routes.
- Keeps the static landing/login/signup assets public so authentication can begin.

### `service/core/config.py`

Added validated auth settings and fail-closed startup behavior. Important variables:

```text
COPILOT_AUTH_REQUIRED
COPILOT_AUTH_COOKIE_SECURE
COPILOT_AUTH_ALLOW_INSECURE_COOKIE
COPILOT_TRUST_ALB_OIDC
COPILOT_COGNITO_REGION
COPILOT_COGNITO_USER_POOL_ID
COPILOT_COGNITO_APP_CLIENT_ID
COPILOT_ALB_ARN
```

Production auth requires a secure cookie. Local HTTP testing may disable it only when `COPILOT_AUTH_ALLOW_INSECURE_COOKIE=1` is also set explicitly.

### `service/auth_dev_app.py`

Added a model-free local FastAPI entrypoint. It mounts the real `/auth/*` router and `/healthz` without importing the unavailable co-pilot model/runtime.

This file stays in the repository. Production does not delete it; production simply runs `service.app:app` instead.

## Frontend implementation

### `frontend/src/lib/amplify.ts`

- Removed Identity Pool, direct S3, direct DynamoDB, and browser AWS-credential responsibilities.
- Configures the public `copilot-spa` User Pool client.
- Uses session storage only for Amplify's temporary OAuth/PKCE and pre-cookie state.
- Exposes the current Cognito ID token only for cookie bootstrap.
- Builds the Cognito Hosted UI logout URL.
- Imports `aws-amplify/auth/enable-oauth-listener` globally so a fresh `/sso-callback` page can exchange the authorization code after a full-page redirect.

### `frontend/src/lib/authenticatedApi.ts`

Centralized the cookie-authenticated API boundary:

- `establishCookieSession()` sends the ID token once to `/auth/session` and then clears temporary Amplify state;
- `getCookieSession()` calls `/auth/me`;
- `logoutCookieSession()` clears the FastAPI cookie and redirects through Cognito logout;
- `authenticatedFetch()` always includes same-origin credentials and redirects expired sessions to `/login`.

The SSE session APIs, video session, demo, ask, and refill-key requests now use credentialed fetch instead of browser AWS credentials.

### Authentication screens

- Signup uses email as the Cognito username, requests email verification, and enables Amplify `autoSignIn`.
- Verification distinguishes two states: Cognito authentication completed vs. FastAPI cookie bootstrap completed.
- Login detects and recovers an existing Amplify session instead of calling Cognito `signIn` twice.
- Google sign-in calls Amplify `signOut()` before changing providers, avoiding `There is already a signed in user` after password auto-sign-in or an interrupted flow.
- Reset-password and confirmation-code state use temporary session storage.
- `/copilot` checks `/auth/me` before rendering the application.
- Sign-out clears local application state, deletes the FastAPI cookie, and ends the Cognito Hosted UI session.

### Google SSO callback

`frontend/src/app/sso-callback/page.tsx` now:

- receives the Cognito callback;
- relies on the globally registered Amplify OAuth listener to exchange the code;
- retries cookie bootstrap for up to five seconds while that asynchronous exchange completes;
- redirects to `/copilot` after the cookie is set;
- displays a real error and return-to-login link instead of remaining indefinitely on `Finishing sign in...`.

The listener fix was necessary because the login-page bundle registered the listener before leaving for Google, but a full-page callback loaded a separate bundle that previously did not register it.

### Removed browser persistence

Removed the direct browser conversation persistence layer:

```text
frontend/src/lib/chatStore.ts
frontend/src/models/conversation.ts
```

The associated direct DynamoDB/S3/Identity Pool packages and environment variables were removed. Conversation-history UI is temporarily disabled until Phase 3 provides FastAPI-owned persistence.

## Next.js local proxy

`frontend/next.config.ts` proxies local development requests to `NEXT_PUBLIC_API_TARGET`:

```text
/auth/*
/me/*
/session
/session/*
/demo
```

The rewrite is for normal/local Next.js mode only. `BUILD_EXPORT=1` generates a static production export without rewrites because the exported frontend and FastAPI are intended to be served from the same origin.

## Local environment

The ignored `frontend/.env.local` uses:

```text
NEXT_PUBLIC_AWS_REGION=ap-southeast-1
NEXT_PUBLIC_COGNITO_USER_POOL_ID=ap-southeast-1_VSo6hlI6k
NEXT_PUBLIC_COGNITO_USER_POOL_CLIENT_ID=5dbs2g7vahmp3tl2ccs280ofsn
NEXT_PUBLIC_COGNITO_DOMAIN=copilot-g4-cos30018-auth.auth.ap-southeast-1.amazoncognito.com
NEXT_PUBLIC_COGNITO_REDIRECT_SIGN_IN=http://localhost:3000/sso-callback
NEXT_PUBLIC_COGNITO_REDIRECT_SIGN_OUT=http://localhost:3000/login
NEXT_PUBLIC_GOOGLE_OAUTH_ENABLED=true
NEXT_PUBLIC_API_TARGET=http://127.0.0.1:8000
```

The ignored `service/.env.local` uses auth-required mode with the same SPA client ID, local in-memory stores, ALB trust disabled, and the explicit insecure-cookie development override.

Never commit either `.env.local` file or the Google client secret.

## Local runbook

The global Python environment initially lacked the JWT verifier even though it was already declared in `requirements-dev.txt`. Local Python 3.14 now has:

```text
PyJWT 2.13.0
cryptography 49.0.0
```

Start the model-free auth server:

```powershell
uvicorn service.auth_dev_app:app --reload --env-file service/.env.local
```

Start the frontend in another terminal:

```powershell
cd frontend
npm run dev
```

Open:

```text
http://localhost:3000/signup
http://localhost:3000/login
```

Currently testable without the model:

- public account creation;
- email confirmation and resend;
- password login;
- password reset;
- Google OAuth;
- ID-token-to-cookie bootstrap;
- `/auth/me` and `/copilot` entry;
- logout and cookie deletion;
- unauthenticated rejection.

Not testable through `auth_dev_app`:

- co-pilot model execution;
- `/session`, `/demo`, SSE generation, artifacts, and assistant behavior.

Those routes intentionally return 404 in the auth-only process because the backend model/box is unavailable.

## Bugs found and fixed during testing

### `There is already a signed in user` after email verification

Cause: `autoSignIn()` succeeded, cookie bootstrap failed, and the UI treated both operations as one failure before inviting the user to sign in again.

Fix: track Cognito sign-in and FastAPI cookie setup separately; retry cookie creation when Cognito is already authenticated. Login also recovers an existing session before issuing a new `signIn`.

### `503 PyJWT[crypto] is required for Cognito auth`

Cause: the Python environment running Uvicorn had FastAPI/Uvicorn but not the declared JWT cryptography dependency.

Fix: installed `PyJWT[crypto]` in that local runtime and verified `PyJWKClient` import.

### `There is already a signed in user` when selecting Google

Cause: stale Amplify tokens from password auto-sign-in or an interrupted bootstrap blocked a provider change.

Fix: call Amplify `signOut()` before `signInWithRedirect({ provider: "Google" })`.

### SSO callback stuck on `Finishing sign in...`

Cause: the callback page did not register Amplify's OAuth completion listener after the full-page redirect.

Fix: globally import the supported OAuth listener and retry cookie bootstrap while code exchange completes.

## Verification completed

- 22 focused backend authentication/ownership tests passed earlier in Phase 1 without live model inference.
- Python authentication modules compile.
- Model-free smoke: `/healthz` returns 200 and unauthenticated `/auth/me` returns 401.
- Frontend ESLint passes after the final auth fixes.
- Next.js TypeScript and production build pass after the final auth fixes.
- CloudFormation change sets were inspected before execution.
- Cognito stack is `UPDATE_COMPLETE`.
- Google IdP and `copilot-spa` provider configuration were verified without exposing secret values.

The final Google callback listener fix still needs one fresh, interactive browser proof from login through `/copilot`; browser control was unavailable during the last automated check.

## Production differences and remaining work

Local testing uses:

```text
Next.js dev rewrite -> auth-only FastAPI -> non-Secure local cookie
```

Target production uses:

```text
HTTPS same origin -> full service.app:app -> Secure __Host-copilot_id cookie
```

Production is not cut over yet because the backend/EC2 box is unavailable. Do not prematurely edit or deploy the ALB/NGINX/box files into a state that is not reflected in AWS.

When the box returns:

1. make NGINX proxy `/auth/*`, `/me/*`, `/session/*`, and `/demo` to FastAPI;
2. preserve `Host`, `X-Forwarded-Host`, `X-Forwarded-Proto`, cookies, and origin information used by same-origin validation;
3. run `service.app:app` with auth required, the SPA client ID, secure cookie enabled, and ALB claim trust disabled for the final architecture;
4. deploy the frontend with Google enabled;
5. test password and Google login, secure cookie bootstrap, `/auth/me`, protected resources, expiry, and logout over `https://inbetween-copilot.click`;
6. remove the ALB `authenticate-cognito` action only after that proof;
7. then remove `copilot-alb` from CloudFormation/Cognito and verify stack/cloud parity.

## Three-phase dependency

```text
Phase 1: verified Cognito cookie identity       <- implemented; production cutover pending
    -> Phase 2: user-scoped session retrieval  <- next; model/GPU not required for ownership proof
    -> Phase 3: conversation/message persistence through FastAPI
```

Cross-phase invariants:

- Cognito `sub` remains the only authoritative internal user identity.
- The browser never supplies authoritative `owner_sub`, `user_id`, database keys, or private S3 prefixes.
- FastAPI owns authentication, authorization, DynamoDB, and S3 access.
- Phase 2 and Phase 3 must reuse this ownership boundary rather than create another identity model.
- Authentication and history tests must remain runnable without the unavailable AI model.

## Teammate continuation checklist

- Read `Vault/05 - Plans and Roadmap/Authentication - Phase 1 Stateless ID Cookie - Implementation.md`.
- Read `frontend/docs/plans/inbetween-copilot-auth-conversations-three-phase-plan.md`.
- Do not expose or retrieve the Google secret value unless an explicit credential operation requires it.
- Do not remove `copilot-alb` while the production listener references it.
- Do not reintroduce browser Identity Pool credentials or direct DynamoDB/S3 clients.
- Restart Next.js after changing any `NEXT_PUBLIC_*` variable.
- Restart Uvicorn after changing `service/.env.local`.
- For callback failures, preserve the exact URL/error and distinguish OAuth code exchange from `/auth/session` cookie bootstrap.
- Keep `infra/10-auth.yaml` and deployed Cognito state synchronized through reviewed CloudFormation change sets.
- After documentation changes, update the local Vault and ask the team to sync the remote vault.
