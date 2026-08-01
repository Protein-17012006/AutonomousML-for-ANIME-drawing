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
  onPair: (p: PairEvent) => void;
  onResult: (r: ResultEvent) => void;
  onError: (msg: string) => void;
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
): Promise<void> {
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
        if (isPairEvent(e.data)) {
          h.onPair(e.data);
          await paintPairProgress();
        } else h.onError("The co-pilot returned an invalid pair event.");
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

/** Grounded session Q&A — answers only from retained session facts.
 *
 * Superseded by askAgent for the chat surface, but kept and still used: the
 * agent is rate-limited and this is not, so a burst of questions degrades to a
 * plain answer instead of an error. */
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

/* ---------------------------------------------------------------------------
 * The agent.
 *
 * /ask answers questions. The agent answers questions AND may propose ONE tool
 * call — which is all it can do: the server decides nothing is executed until
 * the artist accepts it, and refuses proposals it will not honour rather than
 * letting the reply promise something that cannot happen.
 * ------------------------------------------------------------------------- */

export type AgentToolName =
  | "explain_pair"
  | "show_annotated"
  | "open_board"
  | "export_bundle"
  | "rerun_session"
  | "remember_memory";

export interface AgentAction {
  tool: AgentToolName;
  args: Record<string, unknown>;
  /** The server will not run this until the artist explicitly confirms, and it
   *  re-checks on the way in. The UI must never quietly skip it. */
  needs_confirm: boolean;
  label: string;
}

export interface AgentReply {
  say: string;
  grounded: boolean;
  action: AgentAction | null;
  followups: string[];
  /** Present when the model named a tool the server refused. Its prose may
   *  still describe the action, so the artist is told it will not happen
   *  rather than shown a promise with no button. */
  rejected_tool?: string;
}

const TOOL_NAMES: AgentToolName[] = [
  "explain_pair",
  "show_annotated",
  "open_board",
  "export_bundle",
  "rerun_session",
  "remember_memory",
];

function asAction(value: unknown): AgentAction | null {
  if (typeof value !== "object" || value === null) return null;
  const raw = value as Record<string, unknown>;
  if (!TOOL_NAMES.includes(raw.tool as AgentToolName)) return null;
  return {
    tool: raw.tool as AgentToolName,
    args:
      typeof raw.args === "object" && raw.args !== null
        ? (raw.args as Record<string, unknown>)
        : {},
    // Absent or malformed means confirm. Defaulting the other way would let a
    // bad payload run a re-render the artist never asked for.
    needs_confirm: raw.needs_confirm !== false,
    label: typeof raw.label === "string" ? raw.label : "Run",
  };
}

/** One agent turn. The server keeps the chat history, so only the message goes. */
export async function askAgent(
  sid: string,
  message: string,
): Promise<AgentReply> {
  const resp = await authenticatedFetch(`/session/${sid}/agent`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (resp.status === 429) {
    throw new Error("Too many questions at once — give it a moment.");
  }
  if (!resp.ok) throw new Error(`/agent failed: ${resp.status}`);
  const data: unknown = await resp.json();
  if (typeof data !== "object" || data === null) {
    throw new Error("Invalid /agent response");
  }
  const raw = data as Record<string, unknown>;
  return {
    say: typeof raw.say === "string" ? raw.say : "",
    grounded: raw.grounded === true,
    action: asAction(raw.action),
    followups: Array.isArray(raw.followups)
      ? raw.followups.filter((item): item is string => typeof item === "string")
      : [],
    rejected_tool:
      typeof raw.rejected_tool === "string" ? raw.rejected_tool : undefined,
  };
}

/** Re-run the retained keys with changed settings; same SSE contract as /session. */
export async function rerunSession(
  sid: string,
  args: { cadence?: number; smoothness?: number; interpolator?: string },
  h: SessionHandlers,
): Promise<void> {
  const fd = new FormData();
  if (args.cadence != null) fd.append("cadence", String(args.cadence));
  if (args.smoothness != null) fd.append("smoothness", String(args.smoothness));
  if (args.interpolator) fd.append("interpolator", args.interpolator);
  const resp = await authenticatedFetch(`/session/${sid}/rerun`, {
    method: "POST",
    body: fd,
  });
  if (!resp.ok || !resp.body) {
    h.onError(`Re-run failed: ${resp.status}`);
    return;
  }
  await pumpSSE(resp.body, h);
}

/** Save one confirmed preference. The server re-validates key and value. */
export async function rememberMemory(
  args: Record<string, unknown>,
): Promise<void> {
  const resp = await authenticatedFetch("/me/memories", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(args),
  });
  if (!resp.ok) throw new Error(`Could not save that (${resp.status}).`);
}
