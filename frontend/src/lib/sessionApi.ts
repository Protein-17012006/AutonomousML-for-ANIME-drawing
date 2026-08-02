"use client";

import { authenticatedFetch } from "@/lib/authenticatedApi";
import type { PairEvent, ResultEvent } from "@/components/copilot/types";

export interface SessionSummaryCounts {
  n_pairs: number;
  n_autopass: number;
  n_corrected: number;
  flagged: number;
  abstained: number;
  needs_key: number;
}

export interface SessionArtifactLinks {
  montage: string | null;
  report: string | null;
  video: string | null;
}

export interface PublishedSessionSummary {
  pid: string;
  title: string;
  status: "draft" | "complete";
  created_at: string;
  updated_at: string;
  workspace_available: boolean;
  summary: SessionSummaryCounts;
  artifacts: SessionArtifactLinks;
}

export interface SessionListResponse {
  items: PublishedSessionSummary[];
  next_cursor: string | null;
}

export interface SessionWorkspaceSnapshot {
  schema_version: 1;
  upload: {
    mode: "frames" | "video";
    label: string;
    filenames: string[];
  };
  pairs: PairEvent[];
  result: ResultEvent;
  qa: Array<{
    turn_id: string;
    question: string;
    answer: string;
    grounded: boolean;
    answered_at: string;
    /** "ask" for a grounded Q&A turn, "agent" when specialists were involved.
     *  Absent on sessions saved before agent turns were durable. */
    kind?: "ask" | "agent";
    /** Who said what, in order — the planner/triage/perception exchange. */
    transcript?: Array<Record<string, unknown>>;
    action?: Record<string, unknown> | null;
    rejected_tool?: string | null;
  }>;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isCounts(value: unknown): value is SessionSummaryCounts {
  if (!isRecord(value)) return false;
  return [
    "n_pairs",
    "n_autopass",
    "n_corrected",
    "flagged",
    "abstained",
    "needs_key",
  ].every((key) => typeof value[key] === "number");
}

function isArtifacts(value: unknown): value is SessionArtifactLinks {
  return (
    isRecord(value) &&
    isNullableString(value.montage) &&
    isNullableString(value.report) &&
    isNullableString(value.video)
  );
}

function isSession(value: unknown): value is PublishedSessionSummary {
  return (
    isRecord(value) &&
    typeof value.pid === "string" &&
    typeof value.title === "string" &&
    (value.status === "draft" || value.status === "complete") &&
    typeof value.created_at === "string" &&
    typeof value.updated_at === "string" &&
    typeof value.workspace_available === "boolean" &&
    isCounts(value.summary) &&
    isArtifacts(value.artifacts)
  );
}

function isWorkspaceSnapshot(value: unknown): value is SessionWorkspaceSnapshot {
  return (
    isRecord(value) &&
    value.schema_version === 1 &&
    isRecord(value.upload) &&
    (value.upload.mode === "frames" || value.upload.mode === "video") &&
    typeof value.upload.label === "string" &&
    Array.isArray(value.upload.filenames) &&
    value.upload.filenames.every((item) => typeof item === "string") &&
    Array.isArray(value.pairs) &&
    isRecord(value.result) &&
    Array.isArray(value.qa) &&
    value.qa.every((turn) => isRecord(turn) &&
      typeof turn.turn_id === "string" &&
      typeof turn.question === "string" &&
      typeof turn.answer === "string" &&
      typeof turn.grounded === "boolean" &&
      typeof turn.answered_at === "string")
  );
}

async function sessionJson(response: Response): Promise<PublishedSessionSummary> {
  if (!response.ok) {
    throw new Error(`Session request failed (${response.status}).`);
  }
  const value: unknown = await response.json();
  if (!isSession(value)) throw new Error("Invalid session response.");
  return value;
}

function isSessionList(value: unknown): value is SessionListResponse {
  return (
    isRecord(value) &&
    Array.isArray(value.items) &&
    value.items.every(isSession) &&
    isNullableString(value.next_cursor)
  );
}

export async function listMySessions(
  limit = 20,
  cursor?: string,
): Promise<SessionListResponse> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (cursor) params.set("cursor", cursor);
  const response = await authenticatedFetch(`/sessions?${params.toString()}`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Session retrieval failed (${response.status}).`);
  }
  const value: unknown = await response.json();
  if (!isSessionList(value)) throw new Error("Invalid session-list response.");
  return value;
}

export async function getMySession(pid: string): Promise<PublishedSessionSummary> {
  return sessionJson(await authenticatedFetch(`/sessions/${encodeURIComponent(pid)}`, {
    cache: "no-store",
  }));
}

export async function getMySessionWorkspace(pid: string): Promise<SessionWorkspaceSnapshot> {
  const response = await authenticatedFetch(`/sessions/${encodeURIComponent(pid)}/workspace`, {
    cache: "no-store",
  });
  if (!response.ok) throw new Error(`Session workspace request failed (${response.status}).`);
  const value: unknown = await response.json();
  if (!isWorkspaceSnapshot(value)) throw new Error("Invalid session workspace.");
  return value;
}

export interface ResumeOutcome {
  /** The live session id, or null when this saved session cannot be resumed. */
  sid: string | null;
  /** Why not — shown to the artist instead of a bare read-only banner. */
  reason: string | null;
}

/** Turn a saved session back into a working one.
 *
 * A refusal is an ANSWER, not a failure: sessions published before their source
 * keys were durable simply cannot be resumed, and the workbench then stays
 * read-only with the reason on screen. Only an unexpected status throws.
 */
export async function resumeMySession(pid: string): Promise<ResumeOutcome> {
  const response = await authenticatedFetch(
    `/session/resume/${encodeURIComponent(pid)}`,
    { method: "POST" },
  );
  if (response.status === 409 || response.status === 404) {
    const body: unknown = await response.json().catch(() => null);
    const detail = isRecord(body) && typeof body.detail === "string" ? body.detail : null;
    return { sid: null, reason: detail ?? "This saved session cannot be reopened for editing." };
  }
  if (!response.ok) throw new Error(`Could not reopen this session (${response.status}).`);
  const value: unknown = await response.json();
  if (!isRecord(value) || value.sid == null) throw new Error("Invalid resume response.");
  return { sid: String(value.sid), reason: null };
}

export async function createMySession(title: string): Promise<PublishedSessionSummary> {
  return sessionJson(await authenticatedFetch("/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  }));
}

export async function renameMySession(
  pid: string,
  title: string,
): Promise<PublishedSessionSummary> {
  return sessionJson(await authenticatedFetch(`/sessions/${encodeURIComponent(pid)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  }));
}

export async function deleteMySession(pid: string): Promise<void> {
  const response = await authenticatedFetch(`/sessions/${encodeURIComponent(pid)}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw new Error(`Could not delete session (${response.status}).`);
  }
}
