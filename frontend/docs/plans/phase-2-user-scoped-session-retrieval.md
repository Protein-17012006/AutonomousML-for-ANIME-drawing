---
title: Phase 2 — User-Scoped Session Retrieval
type: implementation-phase
project: AutonomousML for Anime Drawing — In-Between Co-pilot
phase: 2
updated: 2026-07-19
status: sidebar-extension-implemented-locally-awaiting-iam-and-title-migration
depends_on: Phase 1
---

# Phase 2 — User-Scoped Session Retrieval

## Implementation result — 2026-07-19

### Sidebar history extension (2026-07-19)

Phase 2 now includes titled, user-owned drafts and a visible History list in `AppSidebar`.
The plus action creates a DynamoDB draft through FastAPI, the pencil action renames an owned row,
and clicking a session retrieves and development-logs only that selected safe summary. The previous
automatic console table of every session has been removed.

The selected draft's durable `pid` is sent as optional multipart `history_pid` to `/session` and
`/session/video`. FastAPI verifies cookie-derived ownership and draft state before generation. The
numeric `sid` remains process-local for live SSE; after the run, the publisher uploads artifacts and
`workspace.v1.json` under the durable `pid`, then conditionally completes the same DynamoDB row.
Pair events are not written to AWS individually.

The snapshot preserves final pair/result data and safe artifact basenames for future read-only Chat
View/Review Board restoration. This phase only logs the selected summary. Future wiring is specified
in `phase-2-read-only-session-workspace-restoration.md`.

The GSI projection remains unchanged; list queries retain `OwnerSessionsIndex` ordering and
batch-read full rows for title/snapshot metadata. Live IAM execution and the deterministic
legacy-title/status migration remain separate approval gates.

The local code path is implemented. It does not require the model/GPU backend:

- the existing DynamoDB table keeps `pid` as its table partition key;
- `OwnerSessionsIndex` uses `owner_sub` as its partition key and `owner_sort` as its sort key;
- `owner_sort` is `CREATED#{zero-padded epoch}#{pid}`, so an owner query can return newest sessions first without a table scan;
- the existing publisher writes both ownership attributes for authenticated sessions;
- `GET /sessions?limit=20&cursor=...` derives the owner from the verified HttpOnly cookie and returns safe summaries only;
- `GET /sessions/{pid}/artifacts/{name}` rechecks ownership and the trusted artifact manifest before streaming the exact S3 object bytes;
- the protected `/copilot` page renders the owned list in the sidebar and logs only a selected safe summary in development; artifacts remain on-demand;
- `service.auth_dev_app` is the model-free local entrypoint; the same shared history router is also registered by the production `service.app` composition root;
- Boto3 runs on FastAPI and uses the server-side AWS credential chain. No temporary or permanent AWS credentials are sent to the browser.

The one-time migration tool is `scripts/assign_session_owners.py`. Its default eligible usernames
are `luudatphong25@gmail.com`, `hoang`, and `Google_115024632640774298668`; it resolves their real,
distinct Cognito `sub` values, assigns every currently ownerless record with fixed seed `20260719`,
does not overwrite an existing owner, writes a reviewable manifest, checkpoints each conditional
write, and supports conditional rollback from that manifest.

Local verification completed with 13 focused backend tests, frontend lint, a Next.js static export
build, Python compilation, and `git diff --check`. Moto supplied in-memory DynamoDB and S3 test
implementations behind the same Boto3 calls used by the real adapters, so pagination, isolation,
artifact-byte streaming, migration, and rollback were tested without contacting AWS.

The original GSI and owner assignment gates were completed on 2026-07-19. The extension introduces
two new gates: review/execute the expanded runtime IAM policy, then review/apply the deterministic
legacy title/status manifest. Neither new live mutation was executed by this implementation pass.

## Objective

Prove that the authenticated Cognito identity established in Phase 1 can safely retrieve only the current user's existing sessions and their artifact references.

The current storage model is:

```text
DynamoDB session metadata
    → session ID and artifact location/prefix
    → existing S3 artifact bucket
    → outputs from previous co-pilot sessions
```

Phase 2 adds ownership to the session metadata, exposes a protected backend listing path, and verifies multi-user isolation without starting a new GPU run.

The immediate frontend proof is intentionally simple:

```text
sign in
    → call authenticated session-list endpoint
    → backend derives user_sub from the validated ID-token cookie
    → backend returns only owned sessions
    → frontend console-logs the returned session summaries in development
```

## Prerequisite

Phase 1 must already provide:

- correctly configured Amplify Auth;
- a validated ID-token contract;
- cookie-backed `authenticatedFetch()` and `/auth/me`;
- FastAPI `AuthContext.user_sub`;
- no direct frontend S3/DynamoDB access.

Do not create a parallel authentication mechanism for this phase.

## Scope

### Included

- Inspection of the existing DynamoDB session repository and S3 artifact layout.
- Addition of `owner_sub` to session metadata.
- Controlled assignment of selected legacy sessions to test users in a non-production environment.
- A user-scoped session listing query.
- Authenticated backend artifact resolution.
- Development console logging of retrieved sessions.
- Cross-user authorization tests.
- No-GPU integration testing.

### Excluded

- New frame generation.
- GPU-box availability.
- Conversation/message persistence.
- Conversation UI.
- Production migration of all historical records unless separately approved.
- Public or presigned browser access that bypasses ownership checks.

## Task 1 — Inspect current session and artifact persistence

Inspect:

```text
service/sessions/
service/review/
service/infrastructure/publisher.py
session repository ports and adapters
artifact-serving routes
service/core/dependencies.py
service/app.py
infrastructure definitions for the session table and artifact bucket
```

Document:

1. DynamoDB table name and key schema.
2. The item that represents one session.
3. Existing fields for `sid`, timestamps, status, source type, and artifact paths.
4. Whether records already include Cognito identity information.
5. How artifact prefixes are stored.
6. Whether paths are relative keys, S3 URIs, or public URLs.
7. Whether one session can reference multiple artifact groups.
8. How artifact routes currently locate files.
9. Whether artifact routes are protected.
10. Whether metadata writes are fail-soft.
11. Whether the table has an index suitable for listing by user.
12. Whether adding a GSI is permitted by the centrally owned infrastructure.

Produce a short session-storage map before modification.

## Task 2 — Define the session ownership fields

Every newly created or test-migrated session must include:

```text
owner_sub
```

Use the Cognito `sub` claim exactly as supplied by the verified `AuthContext`.

Recommended supporting attributes:

```text
created_at
updated_at
source_type
status
artifact_prefix
conversation_id    # optional until Phase 3
```

For efficient user listing, prefer derived index attributes such as:

```text
GSI_OWNER_PK: USER#{owner_sub}
GSI_OWNER_SK: CREATED#{created_at}#{sid}
```

The exact attribute names must follow the existing repository conventions.

### Ownership rule

For any operation involving `sid`:

```text
load session metadata
    → compare metadata.owner_sub with auth.user_sub
    → continue only when equal
```

The client must never be permitted to choose the authoritative owner.

## Task 3 — Choose the user-listing access pattern

### Preferred production pattern

Add or use a DynamoDB GSI that supports:

```text
owner_sub
    → sessions ordered by created_at
```

This avoids scanning the complete table.

### Temporary proof when a GSI cannot yet be added

For a small non-production fixture only, a scan with an ownership filter may be used behind an explicit development/test flag.

Constraints:

- never expose the unfiltered scan result;
- always filter server-side using `auth.user_sub`;
- impose a strict item/limit bound;
- log that the fallback is temporary;
- remove the scan path or replace it with a GSI before production acceptance.

Do not silently ship a table scan as the permanent implementation.

## Task 4 — Assign legacy sessions to test users safely

The existing historical records may not have `owner_sub`.

"Randomly scope them for testing" must be implemented as a controlled data-fixture operation, not as runtime authorization behavior.

Create a one-time non-production script, for example:

```text
scripts/assign_test_session_owners.py
```

Recommended inputs:

```text
--table
--session-ids
--user-subs
--strategy explicit|round-robin|seeded-random
--seed
--dry-run
--output-manifest
```

Required safeguards:

- default to `--dry-run`;
- require explicit confirmation for writes;
- reject production unless an additional administrative override is provided;
- never overwrite an existing `owner_sub` without an explicit flag;
- use a fixed seed for any random assignment;
- write an audit manifest mapping every `sid` to the assigned `owner_sub`;
- support rollback using the manifest;
- avoid assigning sensitive sessions to arbitrary real users.

A deterministic explicit or round-robin fixture is preferred. Seeded random assignment is acceptable only for disposable test data.

### Legacy policy

Unowned sessions must not be treated as public.

Recommended behavior:

```text
missing owner_sub
    → exclude from normal user listings
    → reject direct user-facing access
```

Administrative migration is a separate privileged operation.

## Task 5 — Add the authenticated session-list API

Add a protected static route that does not collide with existing singular `/session/{sid}` routes.

Recommended route:

```http
GET /sessions
```

Suggested query parameters:

```text
limit
cursor
status       # optional
source_type  # optional
```

Suggested response:

```json
{
  "items": [
    {
      "sid": "string",
      "created_at": "ISO-8601",
      "status": "complete",
      "source_type": "keys | video",
      "artifact_summary": {
        "has_montage": true,
        "has_report": true,
        "has_video": true,
        "has_bundle": true
      }
    }
  ],
  "next_cursor": null
}
```

Do not return:

- raw S3 credentials;
- unrestricted S3 prefixes;
- another user's owner identifier;
- private bucket configuration;
- arbitrary client-usable object keys when backend routes can represent them.

### Backend flow

```text
GET /sessions
    → validate the ID token from the HttpOnly cookie
    → derive auth.user_sub
    → query sessions for that owner
    → validate/normalize metadata
    → optionally verify expected artifact objects
    → return safe session summaries
```

## Task 6 — Protect session detail and artifact routes

The session list alone is not sufficient. A user who guesses a `sid` must still be denied.

Apply ownership checks to all applicable operations:

```text
/session/{sid}/key
/session/{sid}/ask
session detail
review
rerun
feedback
montage
report
reconstructed video
bundle/export
other artifact routes
```

For artifact access:

1. obtain `sid` from the route;
2. load session metadata through the repository;
3. verify `owner_sub`;
4. derive the allowed S3 key from trusted metadata;
5. read or stream the object through the backend.

Never accept an arbitrary S3 key from the client as proof of authorization.

The backend uses the EC2 IAM role for DynamoDB and S3 access.

## Task 7 — Implement the no-GPU frontend proof

Add a small API function, for example:

```text
src/components/copilot/lib/sessionApi.ts
```

Suggested function:

```ts
listMySessions()
```

It must use the Phase 1 authenticated client.

During development, call the endpoint after the Cognito session has been established:

```ts
const sessions = await listMySessions();
console.log("[session-retrieval-test]", sessions);
```

Logging constraints:

- development only;
- do not log the ID-token cookie or claims;
- do not log AWS credentials;
- do not log unrestricted S3 keys;
- include the authenticated user's safe local context only when necessary.

No call to `/session` or `/session/video` is required. The test uses previously stored sessions and therefore does not depend on the GPU box.

Optionally add a developer panel that displays the same safe session summaries. Keep it session-focused; conversion into a conversation browser belongs only to optional Phase 3 if that scope is explicitly reopened.

## Task 8 — Test with at least two users

Prepare:

```text
Test User A
Test User B
owned sessions for A
owned sessions for B
at least one unowned legacy session
```

Required tests:

1. User A lists only A sessions.
2. User B lists only B sessions.
3. User A cannot retrieve B's session by guessed `sid`.
4. User B cannot retrieve A's artifacts.
5. An unauthenticated request returns `401`.
6. An authenticated request with the wrong owner returns `404` or `403` according to the chosen information-disclosure policy.
7. An unowned legacy session is inaccessible.
8. A missing artifact does not bypass ownership and is reported safely.
9. Pagination never crosses user boundaries.
10. The no-GPU frontend call logs only the authorized summaries.

Prefer returning `404` for a session that is absent or belongs to another user when avoiding resource-enumeration leakage is important. Apply the policy consistently.

## Task 9 — Validate existing-session metadata compatibility

Confirm that adding ownership fields does not break:

- current session creation;
- SSE pair/result streaming;
- review lookup;
- artifact publishing;
- export;
- assistant grounding;
- feedback persistence;
- existing architecture tests.

Update the publisher/session repository so all future sessions automatically persist `owner_sub` from `AuthContext`. Do not rely only on the test migration script.

## Deliverables

- Session-storage and artifact-layout audit.
- Session ownership model.
- Non-production ownership-fixture script and manifest.
- User-listing DynamoDB access pattern.
- Protected `GET /sessions` endpoint.
- Ownership checks for session and artifact operations.
- Backend-only artifact resolution.
- Frontend `listMySessions()` client.
- Development console proof.
- Two-user isolation test suite.

## Acceptance criteria

Phase 2 is complete when:

- Existing test sessions contain an explicit `owner_sub`.
- Every newly created session receives `owner_sub` from the verified token.
- The backend can query sessions for the current user.
- A signed-in frontend retrieves and development-logs only that user's sessions.
- The test does not require the GPU box.
- A guessed `sid` cannot bypass ownership.
- S3 artifacts are resolved through FastAPI using trusted metadata.
- Unowned legacy sessions are not public.
- User A cannot see User B's sessions or artifacts.
- The final production path does not rely on an unbounded DynamoDB scan.
- Existing session, review, and architecture tests remain green.

## Rollback boundary

Ownership attributes are additive. The fixture script must produce a manifest that can remove only the attributes it added. API and repository changes should be deployable independently from the data-fixture operation.
