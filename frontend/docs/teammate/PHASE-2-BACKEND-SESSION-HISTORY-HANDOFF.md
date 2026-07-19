# Phase 2 Backend Session-History Handoff

Updated: 2026-07-19 18:45 Asia/Saigon

## Session titles, drafts, and workspace snapshots — implementation extension

This document now covers the Phase 2 sidebar-history extension. The implementation is shared code,
not a development-only mock:

- `service.session_history` owns the list, detail, create, rename, workspace, and artifact routes;
- both `service.auth_dev_app` and production `service.app` register that same router;
- `auth_dev_app` is model-free and can verify authentication plus DynamoDB/S3 history behavior, but
  it intentionally does not expose the GPU `/session` generation workflow;
- production `service.app` accepts the selected draft's `history_pid` on both `/session` and
  `/session/video` and passes it to the publisher.

The browser still never talks to DynamoDB or S3. It sends the HttpOnly application cookie to
FastAPI, and FastAPI derives the authoritative Cognito `sub`.

### Extended routes

```http
GET   /sessions?limit=20&cursor=<optional>
GET   /sessions/{pid}
POST  /sessions                 {"title":"Required title"}
PATCH /sessions/{pid}           {"title":"Renamed title"}
GET   /sessions/{pid}/workspace
GET   /sessions/{pid}/artifacts/{safe-basename}
```

Summaries contain `pid`, `title`, `status`, `created_at`, `updated_at`,
`workspace_available`, aggregate QA counts, and protected artifact URLs. They never contain
`owner_sub`, bucket names, raw S3 keys, or credentials. Titles are whitespace-normalized and must
contain 1–80 characters.

State-changing routes require the same-origin `Origin` check already enforced by
`require_current_user`. A missing or foreign `pid` returns the same `404` response.

### Draft binding to the real generation routes

The sidebar plus button calls `POST /sessions`, which creates an owned DynamoDB row with
`status=draft` and returns its durable `pid`. The frontend includes that value as an optional
multipart form field:

```text
history_pid=<durable draft pid>
```

FastAPI checks that this row belongs to the cookie-derived user and is still a draft before
starting either generation route. The numeric `sid` remains the temporary process-local ID used
by live SSE and `/session/{sid}` routes. At completion, `service.infrastructure.publisher` uses
the verified durable `pid`, uploads under `artifacts/{pid}/`, and conditionally updates that same
row to `status=complete`. A completed or foreign `history_pid` cannot be reused.

Requests that omit `history_pid` remain compatible and publish a separate completed
`Untitled session`.

### Publication and snapshot boundary

Pair events are not written to AWS individually. They continue streaming live over the existing
SSE response and remain in the process-local session repository. After the complete run:

1. final PNG, MP4, and Markdown artifacts are uploaded;
2. `artifacts/{pid}/workspace.v1.json` is uploaded;
3. the DynamoDB row is conditionally completed with counts, artifact manifest, snapshot key, and
   snapshot version.

`workspace.v1.json` contains the safe upload descriptor, final serialized pair events, final
result metadata, explanations, sampling/CSQ state, and artifact basenames. It excludes Cognito
identity, credentials, raw S3 keys, local filesystem paths, temporary `sid` URLs, Q&A turns, and
conversation messages. `GET /sessions/{pid}/workspace` validates the snapshot and rewrites only
manifest-approved basenames to protected FastAPI URLs.

Legacy sessions have `workspace_available=false`; their original event stream cannot be recreated
from aggregate counts.

### Required real-backend deployment work

The backend maintainer should merge/deploy the shared implementation rather than recreate routes:

1. Install the Python dependencies used by production, including Boto3 and PyJWT crypto support.
2. Preserve the existing Cognito and secure-cookie configuration and set:

   ```dotenv
   COPILOT_SESSION_HISTORY_ENABLED=1
   AWS_PUBLISH=1
   AWS_SESSIONS_TABLE=copilot_sessions
   AWS_ARTIFACT_BUCKET=copilot-g4-cos30018-artifacts
   AWS_SESSIONS_OWNER_INDEX=OwnerSessionsIndex
   AWS_REGION=ap-southeast-1
   ```

3. Deploy the locally implemented CloudFormation policy update to the existing box identity. The
   live `copilot-box-publisher` user still has only its old `publish-only` policy; the expanded
   policy currently exists only in `infra/30-data.yaml`:
   - table ARN: `dynamodb:GetItem`, `BatchGetItem`, `PutItem`, `UpdateItem`;
   - `OwnerSessionsIndex` ARN: `dynamodb:Query`;
   - `artifacts/*`: `s3:PutObject`, `s3:GetObject`.
4. Run and review `scripts/assign_session_titles.py` in dry-run mode. Apply its manifest only after
   explicit approval; it conditionally adds deterministic titles and `status=complete` without
   overwriting existing values.
5. Start the real entrypoint with `service.app:app`, not `service.auth_dev_app:app`.
6. Serve the frontend and API over the same HTTPS origin so Secure/HttpOnly cookies and CSRF checks
   remain valid.

### Production acceptance checks

- Login lists only the current user's rows.
- Creating a title produces one newest-first draft row owned by that user.
- Rename persists and a foreign user receives `404`.
- Frame and video runs with `history_pid` use the same DynamoDB `pid` and S3 prefix.
- Pair events still appear live before publication finishes.
- Successful publication changes draft to complete and creates a valid workspace snapshot.
- Failed publication does not mark a partial session complete.
- Workspace and artifact requests recheck ownership and never expose raw AWS coordinates.
- `auth_dev_app` passes CRUD/workspace checks locally; the production host separately verifies GPU
  generation, real credentials, proxy headers, S3 uploads, and the final sidebar refresh.

The future read-only UI hydration work is specified in
`frontend/docs/plans/phase-2-read-only-session-workspace-restoration.md`.

## Purpose

The browser must retrieve durable session history through FastAPI. It must never query DynamoDB
or S3 directly and must never receive AWS credentials, raw object keys, bucket configuration, or
another user's Cognito identity.

```text
Browser
  -> sends the HttpOnly application cookie to FastAPI
  -> FastAPI verifies the Cognito ID token
  -> FastAPI derives the Cognito sub from verified claims
  -> FastAPI queries OwnerSessionsIndex for that sub
  -> FastAPI returns safe session summaries
```

For an artifact, FastAPI verifies the cookie and session owner again, resolves the object from the
trusted DynamoDB artifact manifest, reads the private S3 object, and streams its bytes to the
browser.

## Current implementation state

- `service/session_history/` contains the protected API, DynamoDB catalog, S3 artifact adapter,
  response models, ports, and dependency composition.
- The production `service.app` calls `configure_session_history(app)` and registers the plural
  `/sessions` router before the static frontend mount.
- The model-free `service.auth_dev_app` exposes the same history router for local testing without
  loading the GPU/model stack.
- `OwnerSessionsIndex` is active in `ap-southeast-1` on `copilot_sessions`.
- Its key schema is `owner_sub` (HASH) and `owner_sort` (RANGE).
- All 55 legacy rows have explicit owners: 19 / 18 / 18 across the approved Cognito test users.
- Future authenticated publishing writes both `owner_sub` and `owner_sort`.
- The frontend requests `/sessions` with the application cookie, renders titles in the History
  sidebar, and logs only the selected safe summary in development.

## Complete change set to merge

Merge the complete Phase 2 change set, including:

- `service/session_history/`
- `service/app.py`
- `service/auth_dev_app.py`
- `service/core/auth.py`
- `service/core/config.py`
- `service/infrastructure/publisher.py`
- `service/sessions/api.py`
- `service/sessions/service.py`
- `service/sessions/streaming.py`
- `service/tests/test_auth.py`
- `service/tests/test_session_history.py`
- `service/tests/test_publisher.py`
- `service/tests/test_session_ownership.py`
- `service/tests/test_assign_session_titles.py`
- `service/tests/test_architecture.py`
- `requirements-dev.txt`
- `scripts/assign_session_titles.py`
- `infra/30-data.yaml`
- `infra/deploy.sh`
- `frontend/src/lib/sessionApi.ts`
- `frontend/src/app/copilot/page.tsx`
- `frontend/src/components/common/AppSidebar.tsx`
- `frontend/src/components/copilot/CopilotApp.tsx`
- `frontend/src/components/copilot/api.ts`
- `frontend/next.config.ts`

Do not reimplement a second history router. Both local and production entrypoints should compose
the shared `service.session_history` module.

## Production dependencies

Boto3 must be installed in the production Python environment. It is declared in
`requirements-dev.txt`, but the production deployment/install process must actually consume a
manifest that includes it.

PyJWT crypto support is also required for Cognito signature verification. Merge the current
`service/core/auth.py`: it logs verifier failures without logging tokens and permits a bounded
60-second JWT clock-skew tolerance while continuing to verify signature, issuer, audience,
expiration, subject, and token use. The tolerance fixed a locally reproduced Cognito
`ImmatureSignatureError` for a token whose `iat` was a few seconds ahead.

On Windows/local networks with an inspecting certificate authority, Python must be able to fetch
Cognito's JWKS over verified TLS. `uv --system-certs` is the preferred isolated command below. The
tested system-Python alternative used `pip-system-certs`; do not disable TLS verification.

For a local environment managed by `uv`:

```powershell
$env:UV_CACHE_DIR="$PWD\.tmp\uv-cache-phase2"
uv --system-certs run --with-requirements .\requirements-dev.txt `
  python -m uvicorn service.auth_dev_app:app --reload --env-file .\service\.env.local
```

Using `python -m uvicorn` ensures Uvicorn and Boto3 run under the same Python interpreter.

## Production environment

Set these backend-only values on the FastAPI host:

```dotenv
COPILOT_SESSION_HISTORY_ENABLED=1
AWS_PUBLISH=1
AWS_SESSIONS_TABLE=copilot_sessions
AWS_ARTIFACT_BUCKET=copilot-g4-cos30018-artifacts
AWS_SESSIONS_OWNER_INDEX=OwnerSessionsIndex
AWS_REGION=ap-southeast-1
```

Preserve the existing Cognito cookie configuration:

```dotenv
COPILOT_AUTH_REQUIRED=1
COPILOT_COGNITO_REGION=ap-southeast-1
COPILOT_COGNITO_USER_POOL_ID=<existing-user-pool-id>
COPILOT_COGNITO_APP_CLIENT_ID=<existing-public-spa-client-id>
COPILOT_AUTH_COOKIE_SECURE=1
```

Do not put AWS credentials, table names, bucket names, or backend authorization settings in a
`NEXT_PUBLIC_*` variable.

The reverse proxy must preserve the application cookie and HTTPS forwarding information. The
frontend should use same-origin relative `/sessions` requests in production.

## AWS runtime identity decision (resolved)

`copilot-box-publisher` is the IAM user used by the co-pilot box to publish completed output. A
read-only AWS audit on 2026-07-19 confirmed that its live inline policy is still named
`publish-only` and grants only:

- `s3:PutObject` for generated artifacts;
- `dynamodb:PutItem` for durable session metadata.

The original policy cannot retrieve history. The project owner selected expansion of this
existing identity; the separate-reader alternative below remains only as historical context.

### Selected: expand the current backend identity

This is the implemented local CloudFormation direction, but it is not yet deployed to the live IAM
user. Create and review the CloudFormation change set, obtain the separate infrastructure execution
approval, and then apply these narrowly scoped permissions:

- `dynamodb:Query` on `copilot_sessions/index/OwnerSessionsIndex`;
- `dynamodb:GetItem`, `BatchGetItem`, `PutItem`, and `UpdateItem` on `copilot_sessions`;
- `s3:GetObject` and `PutObject` on `copilot-g4-cos30018-artifacts/artifacts/*`.

The FastAPI process can then use its existing default Boto3 credential chain for publishing and
retrieval. Rename or document the identity/policy because it will no longer be strictly
"publish-only."

### Not selected: use a separate reader identity

This preserves the write-only publisher boundary, but requires an additional code/configuration
seam. `configure_session_history()` and the publisher currently use the default Boto3 credential
chain. To use separate identities, construct explicit Boto3 sessions/profiles for the history and
publisher adapters, and keep both credential sets server-side.

The option is already selected: expand the existing backend identity. Keep the CloudFormation
template and deployed IAM state together. Do not make a console-only permission change that leaves
`infra/30-data.yaml` stale.

## Production routes

```http
GET /sessions?limit=20
GET /sessions?limit=20&cursor=<opaque-cursor>
POST /sessions
GET /sessions/{pid}
PATCH /sessions/{pid}
GET /sessions/{pid}/workspace
GET /sessions/{pid}/artifacts/report.md
GET /sessions/{pid}/artifacts/montage.png
GET /sessions/{pid}/artifacts/reconstructed.mp4
```

`limit` bounds the number of summaries returned. `next_cursor` is an opaque continuation token;
the client passes it back as `cursor` for the next page. The server verifies that the cursor row
belongs to the same authenticated user.

The artifact route accepts only a safe basename and supported suffix. It does not accept an
arbitrary S3 key from the client.

## Deployment

1. Merge the Phase 2 code.
2. Ensure Boto3 is installed in the production environment.
3. Configure the history and Cognito environment variables.
4. Create and review a change set for the pending `infra/30-data.yaml` IAM update; execute it only
   after the separate infrastructure approval.
5. Restart the real production entrypoint:

   ```powershell
   python -m uvicorn service.app:app
   ```

6. Confirm the application is served over HTTPS and the cookie is Secure and HttpOnly.
7. Verify `/sessions` through the browser and directly through an authenticated same-origin HTTP
   request.
8. Run `scripts/assign_session_titles.py` in dry-run mode. Review its manifest and apply only after
   the separate data-migration approval. The live title/status backfill has not been executed.

## Security acceptance checks

- An unauthenticated request to `/sessions` returns `401`.
- Each approved user sees only their assigned sessions.
- A guessed foreign `pid` returns `404`, matching an unknown session.
- An ownerless or malformed row is not exposed.
- Pagination never crosses owner boundaries.
- A missing artifact returns a safe `404`.
- Raw S3 keys, bucket names, `owner_sub`, AWS credentials, and Cognito tokens are not returned.
- Artifact bytes pass through FastAPI rather than a direct browser-to-S3 request.
- Browser/server traffic uses HTTPS in production.

## Focused verification

Run from the repository root:

```powershell
$env:UV_CACHE_DIR="$PWD\.tmp\uv-cache-phase2"
uv --system-certs run --with-requirements requirements-dev.txt `
  python -m pytest `
  service/tests/test_architecture.py `
  service/tests/test_auth.py `
  service/tests/test_session_history.py `
  service/tests/test_publisher.py `
  service/tests/test_session_ownership.py `
  service/tests/test_assign_session_titles.py -q
```

The production-composition and session-history subset passed locally. The repository also contains
tests for two-user isolation, newest-first pagination, foreign cursors, exact artifact streaming,
malformed manifests, owner persistence, migration, and rollback.

## Operational notes

- The GSI and legacy owner migration are already complete; do not rerun
  `scripts/assign_session_owners.py` unless intentionally managing a new ownerless fixture.
- The title/status migration is not complete. Run its dry-run first and preserve the generated
  checkpoint/manifest until apply verification finishes; cleanup is a separate deliberate step.
- The local CloudFormation policy is expanded, but the live `copilot-box-publisher` policy remains
  `publish-only` until the reviewed change set is executed.
- The private migration manifest is retained for audit and conditional rollback.
- The new history routes retrieve existing published outputs only. They do not run the GPU pipeline.
- Conversation/message persistence remains separate from durable output-session history.

## Delivery checklist

- Add and commit this handoff file; it is currently a new untracked repository file.
- Merge the complete backend, frontend contract, migration, test, and infrastructure file list
  above as one compatible Phase 2 change set.
- Do not report the IAM expansion or title/status migration as deployed until each separate gate has
  been approved and verified against live AWS.
