// API layer — talks to the FastAPI co-pilot service (same contract as the old web/app.js).
import type { PairEvent, ResultEvent, DemoResult } from "./types";
import { authenticatedFetch } from "@/lib/authenticatedApi";

interface SSEEvent {
  name: string;
  // SSE payloads are validated server-side; shape depends on event name.
  data: unknown;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isPairEvent(value: unknown): value is PairEvent {
  return isRecord(value) && typeof value.index === "number" && typeof value.action === "string";
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

function isAskResponse(value: unknown): value is { answer: string; grounded: boolean } {
  return isRecord(value) && typeof value.answer === "string" && typeof value.grounded === "boolean";
}

function isDemoResult(value: unknown): value is DemoResult {
  return (
    isRecord(value) &&
    typeof value.video === "string" &&
    typeof value.frames === "number" &&
    typeof value.src === "number" &&
    typeof value.gt === "number"
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
  onPair: (p: PairEvent) => void;
  onResult: (r: ResultEvent) => void;
  onError: (msg: string) => void;
}

/** Read an SSE body to completion, dispatching pair/result/error to the handlers. */
async function pumpSSE(body: ReadableStream<Uint8Array>, h: SessionHandlers): Promise<void> {
  const reader = body.getReader();
  const dec = new TextDecoder();
  let buf = "";
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
        if (isPairEvent(e.data)) h.onPair(e.data);
        else h.onError("The co-pilot returned an invalid pair event.");
      } else if (e.name === "result") {
        if (isResultEvent(e.data)) h.onResult(e.data);
        else h.onError("The co-pilot returned an invalid result event.");
      } else if (e.name === "error") {
        if (isErrorEvent(e.data)) h.onError(e.data.message);
        else h.onError("The co-pilot returned an invalid error event.");
      }
    }
  }
}

/** POST keyframes, stream the SSE decision-log, dispatch each event to handlers. */
export async function runSession(
  files: File[],
  engines: string,
  cadence: string,
  smoothness: string,
  h: SessionHandlers,
): Promise<void> {
  const fd = new FormData();
  for (const f of files) fd.append("keys", f);
  fd.append("engines", engines);
  fd.append("cadence", cadence || "12");
  fd.append("smoothness", smoothness || "2");

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

/** POST a single video; the server decodes + stride-decimates it into keys, then
 *  streams the SAME session SSE as runSession. 422 guard errors arrive as JSON
 *  {detail}, so surface that message (cap / bad-format / too-few-keys). */
export async function runVideoSession(
  video: File,
  stride: string,
  cadence: string,
  smoothness: string,
  engines: string,
  h: SessionHandlers,
): Promise<void> {
  const fd = new FormData();
  fd.append("video", video);
  fd.append("stride", stride || "2");
  fd.append("engines", engines);
  // cadence is derived server-side from the decoded video's native rate — the UI value
  // is still posted (best-effort hint) but the server is free to override it.
  fd.append("cadence", cadence || "12");
  fd.append("smoothness", smoothness || "2");

  const resp = await authenticatedFetch("/session/video", {
    method: "POST",
    body: fd,
  });
  if (!resp.ok || !resp.body) {
    let detail = `POST /session/video failed: ${resp.status}`;
    if (resp.status === 413) {
      // The reverse proxy (nginx client_max_body_size) rejects an oversized upload at the
      // edge before it reaches the API, and its 413 body is HTML — so surface a human
      // message instead of the raw "413". The cap is ~200 MB (a short cut, not a full episode).
      detail = "Video too large to upload (max ~200 MB). Trim it to a short cut (a few seconds to ~2 min) and try again.";
    } else {
      try {
        const j: unknown = await resp.json();
        if (isRecord(j) && typeof j.detail === "string") detail = j.detail;
      } catch { /* body wasn't JSON */ }
    }
    h.onError(detail);
    return;
  }
  await pumpSSE(resp.body, h);
}

/** Planted-error demo cases (labeled): the server plants a stored bad in-between from a
 *  frozen suite and the REAL QA/annotate path judges it — exists because the live gate
 *  yields no natural flags. */
/** Grounded session Q&A — answers ONLY from the retained session facts;
 *  grounded=false marks the deterministic offline fallback. */
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

/** POST a full cut → side-by-side original-vs-RIFE comparison video. */
export async function runDemo(files: File[], engines: string, fps: string): Promise<DemoResult> {
  const fd = new FormData();
  for (const f of files) fd.append("frames", f);
  fd.append("engines", engines);
  fd.append("fps", fps || "48");
  const resp = await authenticatedFetch("/demo", {
    method: "POST",
    body: fd,
  });
  if (!resp.ok) throw new Error(`/demo failed: ${resp.status}`);
  const data: unknown = await resp.json();
  if (!isDemoResult(data)) throw new Error("Invalid /demo response");
  return data;
}
