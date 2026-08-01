"use client";

// The active workspace: an in-progress run the server keeps, so closing the tab
// or reloading does not lose it.
//
// These four routes are the ones the previously deployed bundle called and got
// 404 for, because their backend had never been written. It now exists
// (service/active_workspace/), and this module is the client half rebuilt to the
// same contract, so the shapes here are deliberately conservative: every field
// the UI depends on is validated at the boundary rather than trusted.

import { authenticatedFetch } from "@/lib/authenticatedApi";
import type { SessionWorkspaceSnapshot } from "@/lib/sessionApi";

/**
 * `draft` a run in flight · `complete` it finished · `publish_pending` it
 * finished but saving to history failed and can be retried · `published` it is
 * in history, and `published_pid` says where.
 */
export type ActiveWorkspaceState =
  | "draft"
  | "complete"
  | "publish_pending"
  | "published";

export interface ActiveWorkspaceAsset {
  kind: "input-key" | "input-video";
  name: string;
}

export interface ActiveWorkspace {
  workspace_id: string;
  state: ActiveWorkspaceState;
  /** Bumped whenever the server rewrites `snapshot`; the only signal that a
   *  locally cached copy is stale. */
  revision: number;
  /** Sequence of the last event the server recorded — where a stream resumes. */
  event_sequence: number;
  published_pid: string | null;
  snapshot: SessionWorkspaceSnapshot | null;
  /** The artist's original uploads, for resuming on a device whose local cache
   *  is empty. Each name must have an entry in `artifact_urls`. */
  assets: ActiveWorkspaceAsset[];
  artifact_urls: Record<string, string>;
}

export interface PublishOutcome {
  published: boolean;
  pid?: string | null;
  error?: string | null;
}

export type WorkspaceEventName =
  | "workspace"
  | "pair"
  | "result"
  | "error"
  | "publish";

export interface WorkspaceEvent {
  sequence: number;
  name: WorkspaceEventName;
  data: Record<string, unknown>;
}

const EVENT_NAMES: WorkspaceEventName[] = [
  "workspace",
  "pair",
  "result",
  "error",
  "publish",
];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asAssets(value: unknown): ActiveWorkspaceAsset[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) =>
    isRecord(item) &&
    typeof item.name === "string" &&
    (item.kind === "input-key" || item.kind === "input-video")
      ? [{ kind: item.kind, name: item.name }]
      : [],
  );
}

function asUrlMap(value: unknown): Record<string, string> {
  if (!isRecord(value)) return {};
  return Object.fromEntries(
    Object.entries(value).filter(
      (entry): entry is [string, string] => typeof entry[1] === "string",
    ),
  );
}

function asWorkspace(value: unknown): ActiveWorkspace {
  if (
    !isRecord(value) ||
    typeof value.workspace_id !== "string" ||
    typeof value.state !== "string"
  ) {
    // These two are what every other field hangs off; without them there is
    // nothing coherent to show and guessing would strand the artist silently.
    throw new Error("The server returned an active workspace we cannot read.");
  }
  return {
    workspace_id: value.workspace_id,
    state: value.state as ActiveWorkspaceState,
    revision: typeof value.revision === "number" ? value.revision : 0,
    event_sequence:
      typeof value.event_sequence === "number" ? value.event_sequence : 0,
    published_pid:
      typeof value.published_pid === "string" ? value.published_pid : null,
    snapshot: isRecord(value.snapshot)
      ? (value.snapshot as unknown as SessionWorkspaceSnapshot)
      : null,
    assets: asAssets(value.assets),
    artifact_urls: asUrlMap(value.artifact_urls),
  };
}

/** The caller's open workspace, or null when there is none. */
export async function getActiveWorkspace(): Promise<ActiveWorkspace | null> {
  const response = await authenticatedFetch("/active-workspace", {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Active workspace request failed (${response.status}).`);
  }
  const body: unknown = await response.json();
  if (!isRecord(body) || !("workspace" in body)) {
    throw new Error("The server returned an unreadable active-workspace reply.");
  }
  return body.workspace === null ? null : asWorkspace(body.workspace);
}

/** Throw the workspace away. The artist asked; nothing is kept. */
export async function discardActiveWorkspace(
  workspaceId: string,
): Promise<void> {
  const response = await authenticatedFetch(
    `/active-workspace/${encodeURIComponent(workspaceId)}`,
    { method: "DELETE" },
  );
  if (!response.ok) {
    throw new Error(`Discard failed (${response.status}).`);
  }
}

/**
 * Retry saving a run to history. A refused save comes back as `published:
 * false` with a reason in the body, not as an HTTP error — so the artist can be
 * told what happened and press it again.
 */
export async function publishActiveWorkspace(
  workspaceId: string,
): Promise<PublishOutcome> {
  const response = await authenticatedFetch(
    `/active-workspace/${encodeURIComponent(workspaceId)}/publish`,
    { method: "POST" },
  );
  if (!response.ok) {
    throw new Error(`Publish retry failed (${response.status}).`);
  }
  const body: unknown = await response.json();
  if (!isRecord(body) || typeof body.published !== "boolean") {
    throw new Error("The server returned an unreadable publish reply.");
  }
  return {
    published: body.published,
    pid: typeof body.pid === "string" ? body.pid : null,
    error: typeof body.error === "string" ? body.error : null,
  };
}

export interface WorkspaceStreamHandlers {
  onEvent: (event: WorkspaceEvent) => void;
  onConnectionError?: () => void;
}

/**
 * Follow a workspace from `after`, reconnecting on a dropped connection.
 *
 * Resumption is driven entirely by the SSE `id:` field: the browser hands it
 * back as `lastEventId`, and anything at or below the cursor is dropped, so a
 * reconnect replays exactly the gap and nothing else. Returns a function that
 * stops following and will not reconnect.
 */
export function subscribeToWorkspace(
  workspaceId: string,
  after: number,
  handlers: WorkspaceStreamHandlers,
): () => void {
  let cursor = after;
  let closed = false;
  let source: EventSource | null = null;
  let retry: number | null = null;

  const connect = () => {
    if (closed) return;
    source = new EventSource(
      `/active-workspace/${encodeURIComponent(workspaceId)}/stream?after=${cursor}`,
    );
    for (const name of EVENT_NAMES) {
      source.addEventListener(name, (event) => {
        if (!(event instanceof MessageEvent)) return;
        const sequence = Number(event.lastEventId);
        if (!Number.isSafeInteger(sequence) || sequence <= cursor) return;
        let data: unknown;
        try {
          data = JSON.parse(event.data);
        } catch {
          handlers.onConnectionError?.();
          return;
        }
        if (!isRecord(data)) return;
        cursor = sequence;
        handlers.onEvent({ sequence, name, data });
        // The server stops writing at these too; holding the connection open
        // afterwards would just reconnect against a finished run forever.
        const finished =
          name === "error" || (name === "publish" && data.published === true);
        if (finished) {
          closed = true;
          source?.close();
        }
      });
    }
    source.onerror = () => {
      if (closed) return;
      source?.close();
      retry = window.setTimeout(connect, 1000);
      handlers.onConnectionError?.();
    };
  };

  connect();

  return () => {
    closed = true;
    source?.close();
    if (retry !== null) window.clearTimeout(retry);
  };
}
