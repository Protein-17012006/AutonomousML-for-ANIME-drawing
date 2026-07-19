---
title: Phase 2 — Read-Only Session Workspace Restoration
type: implementation-plan
project: AutonomousML for Anime Drawing — In-Between Co-pilot
status: future-implementation
depends_on: Phase 2 sidebar history and workspace.v1 publication
updated: 2026-07-19
---

# Phase 2 — Read-Only Session Workspace Restoration

## Objective

When the production FastAPI backend is available, selecting a completed owned session should
restore its final Chat View and Review Board from the already persisted `workspace.v1.json`.
Active runs continue using the existing live SSE connection; completed sessions load one final
snapshot and do not replay SSE.

This plan deliberately does not persist conversations or make restored sessions mutable.

## Prerequisites and API contract

- The real backend runs `service.app:app` with history and publishing enabled.
- New completed rows contain `snapshot_key`, `snapshot_version=1`, and
  `workspace_available=true`.
- `GET /sessions/{pid}/workspace` rechecks cookie-derived ownership, validates version 1, and
  rewrites safe artifact basenames to `/sessions/{pid}/artifacts/{name}`.
- The frontend adds `getSessionWorkspace(pid)` using the existing same-origin
  `authenticatedFetch`; it must validate the response before updating UI state.

The version-1 response contains:

```ts
interface SessionWorkspaceSnapshot {
  schema_version: 1;
  upload: {
    mode: "frames" | "video";
    label: string;
    filenames: string[];
  };
  pairs: PairEvent[];
  result: ResultEvent;
}
```

No response may contain `owner_sub`, raw S3 keys, bucket names, credentials, local paths, or a
temporary numeric `sid` URL.

## Frontend wiring

Implement a single completed-session selection transaction in `CopilotApp`:

1. Record the selected `pid`, clear any previous history-load error, and show a non-destructive
   workspace loading state.
2. Fetch `GET /sessions/{pid}` and require `status=complete` plus
   `workspace_available=true`.
3. Fetch and validate `GET /sessions/{pid}/workspace`.
4. Commit the snapshot atomically:
   - `upload` becomes the restored upload bubble/description;
   - `log` becomes `snapshot.pairs`;
   - `result` becomes `snapshot.result`;
   - `qaTurns` becomes empty because conversation persistence is out of scope;
   - `liveSid` and `activeDraftPid` become null;
   - `running` becomes false;
   - `view` defaults to `chat` and `boardFocus` resets.
5. Existing `deriveMessages({upload, log, result, ...})` reconstructs Chat View without a second
   transcript model.
6. Existing `ReviewWorkbench` receives the same restored `log` and `result`, so filters, verdict
   display, sampling, explanations, line test, montage, and reconstruction use the existing board.
7. Browser media elements load protected artifact URLs lazily through FastAPI; no browser AWS SDK
   or presigned direct bucket access is introduced.

Do not clear the currently visible workspace until both summary and snapshot validate. If loading
fails, keep the previous view and surface a retryable error associated with the selected history
row.

## Read-only behavior

For a restored completed session:

- allow Chat View inspection, Chat/Board switching, board navigation, playback, report access, and
  existing bundle export when a protected artifact is available;
- disable add-key/refill, rerun, and grounded `/ask` controls because their original numeric `sid`
  and in-memory repository state no longer exist;
- explain disabled actions with accessible text/tooltips rather than silently failing;
- keep local artist accept/reject marks ephemeral unless a separate durable-review phase is
  approved.

Selecting a draft continues to clear transient state, show Chat Welcome, and set its `pid` as the
next `history_pid`. Selecting a completed session never makes it a run target.

## Failure and compatibility handling

- `401`: redirect through the existing login flow after clearing invalid application auth state.
- `404`: show “Session workspace is unavailable” without revealing whether a foreign session
  exists.
- Unsupported or malformed snapshot: reject the entire payload and keep the prior workspace.
- `workspace_available=false`: show the safe summary and available montage/report/video links only;
  do not fabricate pair events for legacy sessions.
- Missing individual artifact: keep the rest of the snapshot usable and show a local unavailable
  placeholder for that media cell.
- A newer snapshot version must be handled by an explicit version adapter; never guess field
  compatibility.

## Verification

- Snapshot types and runtime validators reject malformed pairs, results, versions, and unsafe URLs.
- User A cannot load User B's summary, workspace, or artifacts.
- Selecting a completed session reconstructs the same Chat View ordering and Review Board rows as
  the final live SSE state.
- Chat/Board switching does not refetch the workspace or open an SSE connection.
- Artifact requests remain same-origin and cookie-authenticated.
- Slow/failing selection does not erase the current workspace or apply stale responses after a
  newer session is selected.
- Restored mode disables every operation requiring `liveSid`.
- Legacy sessions degrade to summary/artifact-only display.
- Run frontend lint, static-export build, focused backend workspace tests, and an authenticated
  production smoke test through the real reverse proxy.

## Explicit exclusions

- Reattaching to an in-progress run after refresh or from another device.
- Persisting/replaying pair events as a resumable SSE log.
- Restored-session refill, rerun, grounded ask, or other durable mutations.
- Conversation and Q&A persistence.
