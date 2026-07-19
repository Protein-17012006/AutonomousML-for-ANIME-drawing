"use client";

import { authenticatedFetch } from "@/lib/authenticatedApi";

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
  created_at: string;
  summary: SessionSummaryCounts;
  artifacts: SessionArtifactLinks;
}

export interface SessionListResponse {
  items: PublishedSessionSummary[];
  next_cursor: string | null;
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
    typeof value.created_at === "string" &&
    isCounts(value.summary) &&
    isArtifacts(value.artifacts)
  );
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

let proofPromise: Promise<void> | null = null;

export function logDevelopmentSessions(): Promise<void> {
  if (process.env.NODE_ENV !== "development") return Promise.resolve();
  if (proofPromise) return proofPromise;
  proofPromise = listMySessions()
    .then((sessions) => {
      console.info(
        `[session-retrieval-test] ${sessions.items.length} authorized sessions`,
      );
      console.table(
        sessions.items.map((session) => ({
          pid: session.pid,
          created_at: session.created_at,
          pairs: session.summary.n_pairs,
          on_model: session.summary.n_autopass,
          corrected: session.summary.n_corrected,
          flagged: session.summary.flagged,
          abstained: session.summary.abstained,
          needs_key: session.summary.needs_key,
        })),
      );
      console.info("[session-retrieval-test] response", sessions);
    })
    .catch((error: unknown) => {
      console.warn("[session-retrieval-test] unavailable", error);
    });
  return proofPromise;
}
