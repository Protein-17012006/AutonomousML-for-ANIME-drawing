"use client";

import { authenticatedFetch } from "@/lib/authenticatedApi";

export interface ActiveWorkspace {
  workspace_id: string;
  state: "generating" | "ready" | "publish_pending" | "published" | "failed";
  revision: number;
  event_sequence: number;
  expires_at: number;
  history_pid: string | null;
  published_pid: string | null;
  snapshot: {
    upload?: { mode?: "frames" | "video"; label?: string; filenames?: string[] };
    pairs?: unknown[];
    result?: unknown;
  };
  assets: Array<{ name: string; kind: "input-key" | "input-video" | "generated" }>;
  artifact_urls: Record<string, string>;
}

export interface ActiveWorkspaceEvent {
  sequence: number;
  name: "workspace" | "pair" | "result" | "error" | "publish";
  data: Record<string, unknown>;
}

export interface ActiveWorkspaceSubscription {
  onEvent: (event: ActiveWorkspaceEvent) => void;
  onConnectionError?: () => void;
}

function isWorkspace(value: unknown): value is ActiveWorkspace {
  return typeof value === "object" && value !== null &&
    typeof (value as ActiveWorkspace).workspace_id === "string" &&
    typeof (value as ActiveWorkspace).state === "string";
}

export async function getActiveWorkspace(): Promise<ActiveWorkspace | null> {
  const response = await authenticatedFetch("/active-workspace", { cache: "no-store" });
  if (!response.ok) throw new Error(`Active workspace request failed (${response.status}).`);
  const value: unknown = await response.json();
  if (typeof value !== "object" || value === null || !("workspace" in value)) {
    throw new Error("Invalid active workspace response.");
  }
  const workspace = (value as { workspace: unknown }).workspace;
  if (workspace === null) return null;
  if (!isWorkspace(workspace)) throw new Error("Invalid active workspace.");
  return workspace;
}

export async function discardActiveWorkspace(workspaceId: string) {
  const response = await authenticatedFetch(`/active-workspace/${encodeURIComponent(workspaceId)}`, {
    method: "DELETE",
  });
  if (!response.ok) throw new Error(`Discard failed (${response.status}).`);
}

export async function retryActiveWorkspacePublish(workspaceId: string) {
  const response = await authenticatedFetch(`/active-workspace/${encodeURIComponent(workspaceId)}/publish`, {
    method: "POST",
  });
  if (!response.ok) throw new Error(`Publish retry failed (${response.status}).`);
  return response.json() as Promise<{ published: boolean; pid?: string | null; error?: string | null }>;
}

/** Subscribe from the last persisted journal sequence. The server replays every
 * missed event before registering this browser for new ones. */
export function subscribeActiveWorkspace(
  workspaceId: string,
  after: number,
  handlers: ActiveWorkspaceSubscription,
) {
  let closed = false;
  let source: EventSource | null = null;
  let lastSequence = after;
  let retryTimer: number | null = null;

  const connect = () => {
    if (closed) return;
    source = new EventSource(
      `/active-workspace/${encodeURIComponent(workspaceId)}/stream?after=${lastSequence}`,
    );
    for (const name of ["workspace", "pair", "result", "error", "publish"] as const) {
      source.addEventListener(name, (message) => {
        if (!(message instanceof MessageEvent)) return;
        const sequence = Number(message.lastEventId);
        if (!Number.isSafeInteger(sequence) || sequence <= lastSequence) return;
        try {
          const data: unknown = JSON.parse(message.data);
          if (typeof data !== "object" || data === null || Array.isArray(data)) return;
          const payload = data as Record<string, unknown>;
          lastSequence = sequence;
          handlers.onEvent({ sequence, name, data: payload });
          if (name === "error" || (name === "publish" && payload.published === true)) {
            closed = true;
            source?.close();
          }
        } catch {
          handlers.onConnectionError?.();
        }
      });
    }
    source.onerror = () => {
      if (closed) return;
      source?.close();
      retryTimer = window.setTimeout(connect, 1_000);
      handlers.onConnectionError?.();
    };
  };

  connect();
  return () => {
    closed = true;
    source?.close();
    if (retryTimer !== null) window.clearTimeout(retryTimer);
  };
}
