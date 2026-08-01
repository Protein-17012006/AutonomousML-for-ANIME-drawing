// API layer — talks to the FastAPI co-pilot service (same contract as the old web/app.js).
import type { PairEvent, ResultEvent } from "./types";
import { authenticatedFetch } from "@/lib/authenticatedApi";

interface SSEEvent {
  name: string;
  data: unknown;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
function isPairEvent(value: unknown): value is PairEvent {
  return (
    isRecord(value) &&
    typeof value.index === "number" &&
    typeof value.action === "string"
  );
}
function isResultEvent(value: unknown): value is ResultEvent {
  return (
    isRecord(value) &&
    typeof value.n_autopass === "number" &&
    typeof value.n_corrected === "number" &&
    typeof value.keys_requested_total === "number" &&
    Array.isArray(value.flagged) &&
    Array.isArray(value.abstained)
  );
}
function isErrorEvent(value: unknown): value is { message: string } {
  return isRecord(value) && typeof value.message === "string";
}
function isPublishEvent(value: unknown): value is { published: boolean; pid?: string; error?: string } {
  return isRecord(value) && typeof value.published === "boolean" &&
    (value.pid === undefined || typeof value.pid === "string") &&
    (value.error === undefined || typeof value.error === "string");
}
function isAskResponse(
  value: unknown,
): value is { answer: string; grounded: boolean } {
  return (
    isRecord(value) &&
    typeof value.answer === "string" &&
    typeof value.grounded === "boolean"
  );
}

export function parseSSE(buffer: string): { events: SSEEvent[]; rest: string } {
  const events: SSEEvent[] = [];
  let rest = buffer.replaceAll("\r\n", "\n");
  let idx: number;
  while ((idx = rest.indexOf("\n\n")) !== -1) {
    const block = rest.slice(0, idx);
    rest = rest.slice(idx + 2);
    let name = "message";
    let data = "";
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) name = line.slice(6).trim();
      else if (line.startsWith("data:")) data += line.slice(5).trim();
    }
    if (data) events.push({ name, data: JSON.parse(data) as unknown });
  }
  return { events, rest };
}

export interface SessionHandlers {
  onPair: (p: PairEvent) => void | Promise<void>;
  onResult: (r: ResultEvent) => void | Promise<void>;
  onError: (msg: string) => void;
  onPublish?: (event: { published: boolean; pid?: string; error?: string }) => void;
  onProgress?: (phase: string) => void;
}

/** Give React a paint opportunity after a streamed pair update. A proxy can
 * coalesce several valid SSE blocks into one read, otherwise React batches all
 * `onPair` state updates and the artist sees only the final pair count. */
function paintPairProgress(): Promise<void> {
  if (
    typeof window === "undefined" ||
    typeof window.requestAnimationFrame !== "function"
  ) {
    return Promise.resolve();
  }
  return new Promise((resolve) =>
    window.requestAnimationFrame(() => resolve()),
  );
}

/** Read an SSE body to completion, dispatching pair/result/error to handlers. */
async function pumpSSE(
  body: ReadableStream<Uint8Array>,
  h: SessionHandlers,
  { stopAfterResult = false }: { stopAfterResult?: boolean } = {},
): Promise<void> {
  const reader = body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  let terminal = false;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let events: SSEEvent[];
    let rest: string;
    try {
      ({ events, rest } = parseSSE(buf));
    } catch {
      h.onError("The co-pilot returned an invalid stream event.");
      return;
    }
    buf = rest;
    for (const e of events) {
      if (e.name === "pair") {
        if (isPairEvent(e.data)) {
          await h.onPair(e.data);
          await paintPairProgress();
        } else h.onError("The co-pilot returned an invalid pair event.");
      } else if (e.name === "result") {
        if (isResultEvent(e.data)) {
          terminal = true;
          await h.onResult(e.data);
          // Review revisions have no later publish event: their result is
          // emitted only after the durable revision commits. Stop here so a
          // transport close after successful hydration cannot overwrite that
          // success with a misleading browser "network error".
          if (stopAfterResult) return;
        }
        else h.onError("The co-pilot returned an invalid result event.");
      } else if (e.name === "error") {
        terminal = true;
        if (isErrorEvent(e.data)) h.onError(e.data.message);
        else h.onError("The co-pilot returned an invalid error event.");
      } else if (e.name === "publish") {
        if (isPublishEvent(e.data)) h.onPublish?.(e.data);
        else h.onError("The co-pilot returned an invalid publish event.");
      } else if (e.name === "progress" && isRecord(e.data) && typeof e.data.phase === "string") {
        h.onProgress?.(e.data.phase);
      }
    }
  }
  if (!terminal) h.onError("The co-pilot stream ended before it returned a result.");
}

export async function submitVerdicts(
  sid: string,
  verdicts: Record<number, "accept" | "reject">,
  h: SessionHandlers,
): Promise<void> {
  try {
    const resp = await authenticatedFetch(`/session/${sid}/feedback/batch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ verdicts: Object.entries(verdicts).map(([pair_index, verdict]) => ({ pair_index: Number(pair_index), verdict })) }),
    });
    if (!resp.ok || !resp.body) {
      h.onError(`Submit verdicts failed: ${resp.status}`);
      return;
    }
    await pumpSSE(resp.body, h, { stopAfterResult: true });
  } catch (error) {
    h.onError(error instanceof Error ? `Submit verdicts failed: ${error.message}` : "Submit verdicts failed.");
  }
}

export async function submitReplacementKeys(
  sid: string,
  keys: Record<number, File>,
  h: SessionHandlers,
): Promise<void> {
  try {
    const body = new FormData();
    for (const [index, file] of Object.entries(keys)) {
      body.append("indices", index);
      body.append("keys", file);
    }
    const resp = await authenticatedFetch(`/session/${sid}/keys`, { method: "POST", body });
    if (!resp.ok || !resp.body) {
      h.onError(`Submit replacement keys failed: ${resp.status}`);
      return;
    }
    await pumpSSE(resp.body, h, { stopAfterResult: true });
  } catch (error) {
    h.onError(error instanceof Error ? `Submit replacement keys failed: ${error.message}` : "Submit replacement keys failed.");
  }
}

/** POST keyframes, stream the SSE decision-log, dispatch each event to handlers. */
export async function runSession(
  files: File[],
  engines: string,
  interpolator: string,
  cadence: string,
  smoothness: string,
  h: SessionHandlers,
  historyPid?: string | null,
): Promise<void> {
  const fd = new FormData();
  for (const f of files) fd.append("keys", f);
  fd.append("engines", engines);
  fd.append("interpolator", interpolator);
  fd.append("cadence", cadence || "12");
  fd.append("smoothness", smoothness || "2");
  if (historyPid) fd.append("history_pid", historyPid);
  const resp = await authenticatedFetch("/session", {
    method: "POST",
    body: fd,
  });
  if (!resp.ok || !resp.body) {
    h.onError(`POST /session failed: ${resp.status}`);
    return;
  }
  await pumpSSE(resp.body, h);
}

/** POST a single video; the server decodes + stride-decimates it into keys, then streams the same session SSE. */
export async function runVideoSession(
  video: File,
  stride: string,
  cadence: string,
  smoothness: string,
  engines: string,
  interpolator: string,
  h: SessionHandlers,
  historyPid?: string | null,
): Promise<void> {
  const fd = new FormData();
  fd.append("video", video);
  fd.append("stride", stride || "2");
  fd.append("engines", engines);
  fd.append("interpolator", interpolator);
  fd.append("cadence", cadence || "12");
  fd.append("smoothness", smoothness || "2");
  if (historyPid) fd.append("history_pid", historyPid);
  const resp = await authenticatedFetch("/session/video", {
    method: "POST",
    body: fd,
  });
  if (!resp.ok || !resp.body) {
    let detail = `POST /session/video failed: ${resp.status}`;
    if (resp.status === 413)
      detail =
        "Video too large to upload (max ~200 MB). Trim it to a short cut (a few seconds to ~2 min) and try again.";
    else {
      try {
        const j: unknown = await resp.json();
        if (isRecord(j) && typeof j.detail === "string") detail = j.detail;
      } catch {
        /* body wasn't JSON */
      }
    }
    h.onError(detail);
    return;
  }
  await pumpSSE(resp.body, h);
}

/** Grounded session Q&A — answers only from retained session facts. */
export async function askQuestion(
  sid: string,
  question: string,
): Promise<{ answer: string; grounded: boolean }> {
  const resp = await authenticatedFetch(`/session/${sid}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  if (!resp.ok) throw new Error(`/ask failed: ${resp.status}`);
  const data: unknown = await resp.json();
  if (!isAskResponse(data)) throw new Error("Invalid /ask response");
  return data;
}
