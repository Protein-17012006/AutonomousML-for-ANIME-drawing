// API layer — talks to the FastAPI co-pilot service (same contract as the old web/app.js).
import type { PairEvent, ResultEvent, DemoResult } from "./types";
import { authHeaders } from "@/lib/amplify";

interface SSEEvent {
  name: string;
  // SSE payloads are validated server-side; shape depends on event name.
  data: PairEvent | ResultEvent | { message: string };
}

export function parseSSE(buffer: string): { events: SSEEvent[]; rest: string } {
  const events: SSEEvent[] = [];
  let rest = buffer;
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
    if (data) events.push({ name, data: JSON.parse(data) });
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
    const { events, rest } = parseSSE(buf);
    buf = rest;
    for (const e of events) {
      if (e.name === "pair") h.onPair(e.data as PairEvent);
      else if (e.name === "result") h.onResult(e.data as ResultEvent);
      else if (e.name === "error") h.onError((e.data as { message: string }).message);
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

  const resp = await fetch("/session", {
    method: "POST",
    headers: await authHeaders(),
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

  const resp = await fetch("/session/video", {
    method: "POST",
    headers: await authHeaders(),
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
        const j = (await resp.json()) as { detail?: string };
        if (j?.detail) detail = j.detail;
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
export type PlantedCase = { id: string; title: string; planted_type: string };

export async function fetchPlantedCases(): Promise<PlantedCase[]> {
  const resp = await fetch("/session/planted/cases", { headers: await authHeaders() });
  if (!resp.ok) return [];
  return ((await resp.json()) as { cases: PlantedCase[] }).cases ?? [];
}

export async function runPlantedSession(
  caseId: string,
  engines: string,
  cadence: string,
  smoothness: string,
  h: SessionHandlers,
): Promise<void> {
  const fd = new FormData();
  fd.append("case", caseId);
  fd.append("engines", engines);
  fd.append("cadence", cadence || "12");
  fd.append("smoothness", smoothness || "2");
  const resp = await fetch("/session/planted", {
    method: "POST",
    headers: await authHeaders(),
    body: fd,
  });
  if (!resp.ok || !resp.body) {
    h.onError(`POST /session/planted failed: ${resp.status}`);
    return;
  }
  await pumpSSE(resp.body, h);
}

/** Grounded session Q&A — answers ONLY from the retained session facts;
 *  grounded=false marks the deterministic offline fallback. */
export async function askQuestion(
  sid: string,
  question: string,
): Promise<{ answer: string; grounded: boolean }> {
  const resp = await fetch(`/session/${sid}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify({ question }),
  });
  if (!resp.ok) throw new Error(`/ask failed: ${resp.status}`);
  return (await resp.json()) as { answer: string; grounded: boolean };
}

/** POST a full cut → side-by-side original-vs-RIFE comparison video. */
export async function runDemo(files: File[], engines: string, fps: string): Promise<DemoResult> {
  const fd = new FormData();
  for (const f of files) fd.append("frames", f);
  fd.append("engines", engines);
  fd.append("fps", fps || "48");
  const resp = await fetch("/demo", {
    method: "POST",
    headers: await authHeaders(),
    body: fd,
  });
  if (!resp.ok) throw new Error(`/demo failed: ${resp.status}`);
  return (await resp.json()) as DemoResult;
}
