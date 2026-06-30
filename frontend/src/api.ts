// API layer — talks to the FastAPI co-pilot service (same contract as the old web/app.js).
import type { PairEvent, ResultEvent, DemoResult } from "./types";

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
  fps: string,
  h: SessionHandlers,
): Promise<void> {
  const fd = new FormData();
  for (const f of files) fd.append("keys", f);
  fd.append("engines", engines);
  fd.append("fps", fps || "24");

  const resp = await fetch("/session", { method: "POST", body: fd });
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
  fps: string,
  engines: string,
  h: SessionHandlers,
): Promise<void> {
  const fd = new FormData();
  fd.append("video", video);
  fd.append("stride", stride || "2");
  fd.append("engines", engines);
  fd.append("fps", fps || "24");

  const resp = await fetch("/session/video", { method: "POST", body: fd });
  if (!resp.ok || !resp.body) {
    let detail = `POST /session/video failed: ${resp.status}`;
    try {
      const j = (await resp.json()) as { detail?: string };
      if (j?.detail) detail = j.detail;
    } catch { /* body wasn't JSON */ }
    h.onError(detail);
    return;
  }
  await pumpSSE(resp.body, h);
}

/** POST a full cut → side-by-side original-vs-RIFE comparison video. */
export async function runDemo(files: File[], engines: string, fps: string): Promise<DemoResult> {
  const fd = new FormData();
  for (const f of files) fd.append("frames", f);
  fd.append("engines", engines);
  fd.append("fps", fps || "48");
  const resp = await fetch("/demo", { method: "POST", body: fd });
  if (!resp.ok) throw new Error(`/demo failed: ${resp.status}`);
  return (await resp.json()) as DemoResult;
}
