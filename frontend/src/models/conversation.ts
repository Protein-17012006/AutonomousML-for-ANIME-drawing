import type { PairEvent, ResultEvent } from "@/components/copilot/types";
import type { QaTurn, UserTurn } from "@/components/copilot/lib/chatModel";

export type SessionKind = "png" | "video" | "planted";

export interface ConversationMeta {
  identityId: string;
  sk: string;
  cid: string;
  title: string;
  kind: SessionKind;
  engines: string;
  fps: number;
  stride: number;
  sid?: string | null;
  uploadLabel: string;
  thumb?: string | null;
  createdAt: number;
  updatedAt: number;
  schemaVersion: 1;
}

export interface ConversationState {
  schemaVersion: 1;
  upload: UserTurn | null;
  log: PairEvent[];
  result: ResultEvent | null;
  qaTurns: QaTurn[];
  verdicts: Record<number, "accept" | "reject">;
}

export interface PersistSessionInput {
  cid: string;
  identityId: string;
  state: ConversationState;
  keyFiles: File[];
  videoFile?: File | null;
  onProgress?: (done: number, total: number) => void;
}
