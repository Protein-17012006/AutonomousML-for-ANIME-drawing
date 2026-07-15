"use client";

import {
  DeleteCommand,
  PutCommand,
  QueryCommand,
  UpdateCommand,
} from "@aws-sdk/lib-dynamodb";
import type {
  ConversationMeta,
  ConversationState,
  PersistSessionInput,
  SessionKind,
} from "@/models/conversation";
import type { PairEvent, ResultEvent } from "@/components/copilot/types";
import {
  chatsTableName,
  getDynamoDoc,
  getSignedStorageUrl,
  markS3Key,
  putStorageObject,
  removeStorageObject,
  storageKey,
  unmarkS3Key,
} from "@/lib/amplify";

const SCHEMA_VERSION = 1 as const;

export function newConversationId() {
  const cryptoApi = globalThis.crypto;
  if (typeof cryptoApi?.randomUUID === "function") {
    return cryptoApi.randomUUID();
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export function conversationSk(cid: string) {
  return `CONV#${cid}`;
}

export async function listConversations(identityId: string): Promise<ConversationMeta[]> {
  const doc = await getDynamoDoc();
  const res = await doc.send(
    new QueryCommand({
      TableName: chatsTableName(),
      KeyConditionExpression: "identityId = :identityId",
      ExpressionAttributeValues: {
        ":identityId": identityId,
      },
    }),
  );

  return ((res.Items ?? []) as ConversationMeta[])
    .filter((item) => item.sk?.startsWith("CONV#"))
    .sort((a, b) => b.updatedAt - a.updatedAt);
}

export async function createConversation(meta: ConversationMeta) {
  const doc = await getDynamoDoc();
  await doc.send(
    new PutCommand({
      TableName: chatsTableName(),
      Item: meta,
    }),
  );
}

export async function updateConversationMeta(
  identityId: string,
  cid: string,
  patch: Partial<Omit<ConversationMeta, "identityId" | "sk" | "cid">>,
) {
  const entries = Object.entries(patch).filter(([, value]) => value !== undefined);
  if (!entries.length) return;

  const names: Record<string, string> = {};
  const values: Record<string, unknown> = {};
  const sets = entries.map(([key, value], index) => {
    const nk = `#k${index}`;
    const vk = `:v${index}`;
    names[nk] = key;
    values[vk] = value;
    return `${nk} = ${vk}`;
  });

  const doc = await getDynamoDoc();
  await doc.send(
    new UpdateCommand({
      TableName: chatsTableName(),
      Key: { identityId, sk: conversationSk(cid) },
      UpdateExpression: `SET ${sets.join(", ")}`,
      ExpressionAttributeNames: names,
      ExpressionAttributeValues: values,
    }),
  );
}

export async function deleteConversation(identityId: string, cid: string) {
  const doc = await getDynamoDoc();
  await doc.send(
    new DeleteCommand({
      TableName: chatsTableName(),
      Key: { identityId, sk: conversationSk(cid) },
    }),
  );

  // Best effort: remove state. The object fan-out is deterministic but may include many generated
  // frames; S3 lifecycle / future prefix delete can clean up any leftover frame objects.
  await removeStorageObject(storageKey(identityId, cid, "state.json")).catch(() => undefined);
}

function jsonBlob(data: unknown) {
  return new Blob([JSON.stringify(data)], { type: "application/json" });
}

export async function putConversationState(
  identityId: string,
  cid: string,
  state: ConversationState,
) {
  await putStorageObject(
    storageKey(identityId, cid, "state.json"),
    jsonBlob(stripSignedUrls(state)),
    "application/json",
  );
}

export async function getConversationState(
  identityId: string,
  cid: string,
): Promise<ConversationState> {
  const { getStorageText } = await import("@/lib/amplify");
  const raw = await getStorageText(storageKey(identityId, cid, "state.json"));
  const state = JSON.parse(raw) as ConversationState;
  return resolveSignedUrls(state);
}

async function uploadFromUrl(
  identityId: string,
  cid: string,
  sourceUrl: string,
  targetName: string,
) {
  const resp = await fetch(sourceUrl);
  if (!resp.ok) throw new Error(`Failed to fetch ${sourceUrl}: ${resp.status}`);
  const blob = await resp.blob();
  const key = storageKey(identityId, cid, targetName);
  await putStorageObject(key, blob, blob.type || undefined);
  return markS3Key(key);
}

function collectServerUrls(state: ConversationState) {
  const urls = new Map<string, string>();
  const add = (url: string | null | undefined, target: string) => {
    if (!url || url.startsWith("s3key:") || urls.has(url)) return;
    if (!url.startsWith("/session/")) return;
    urls.set(url, target);
  };

  state.log.forEach((p) => add(p.mid_url, `mids/pair-${p.index}.png`));
  const result = state.result;
  if (!result) return urls;

  Object.entries(result.explanations ?? {}).forEach(([idx, ex]) => {
    add(ex.annotated_url, `annotated/pair-${idx}.png`);
  });
  Object.entries(result.pair_mids ?? {}).forEach(([idx, url]) => {
    add(url, `pair_mids/${idx}.png`);
  });
  Object.entries(result.key_urls ?? {}).forEach(([idx, url]) => {
    add(url, `keys/${idx}.png`);
  });
  add(result.artifacts?.montage, "montage.png");
  add(result.artifacts?.video, "video.mp4");
  add(result.artifacts?.report, "report.md");

  return urls;
}

function replaceUrlInResult(result: ResultEvent, from: string, to: string): ResultEvent {
  return {
    ...result,
    artifacts: result.artifacts
      ? {
          montage: result.artifacts.montage === from ? to : result.artifacts.montage,
          video: result.artifacts.video === from ? to : result.artifacts.video,
          report: result.artifacts.report === from ? to : result.artifacts.report,
        }
      : result.artifacts,
    explanations: result.explanations
      ? Object.fromEntries(
          Object.entries(result.explanations).map(([idx, ex]) => [
            idx,
            {
              ...ex,
              annotated_url: ex.annotated_url === from ? to : ex.annotated_url,
            },
          ]),
        )
      : result.explanations,
    pair_mids: result.pair_mids
      ? Object.fromEntries(
          Object.entries(result.pair_mids).map(([idx, url]) => [idx, url === from ? to : url]),
        )
      : result.pair_mids,
    key_urls: result.key_urls
      ? Object.fromEntries(
          Object.entries(result.key_urls).map(([idx, url]) => [idx, url === from ? to : url]),
        )
      : result.key_urls,
  };
}

function replaceUrl(state: ConversationState, from: string, to: string): ConversationState {
  return {
    ...state,
    log: state.log.map((p): PairEvent => ({
      ...p,
      mid_url: p.mid_url === from ? to : p.mid_url,
    })),
    result: state.result ? replaceUrlInResult(state.result, from, to) : state.result,
  };
}

export async function persistSessionImages(input: PersistSessionInput): Promise<ConversationState> {
  let state: ConversationState = {
    ...input.state,
    schemaVersion: SCHEMA_VERSION,
  };
  const uploads: Array<Promise<void>> = [];
  let completed = 0;

  const serverUrls = collectServerUrls(state);
  const total = input.keyFiles.length + (input.videoFile ? 1 : 0) + serverUrls.size;
  const tick = () => {
    completed += 1;
    input.onProgress?.(completed, total);
  };

  input.keyFiles.forEach((file, index) => {
    const key = storageKey(input.identityId, input.cid, `keys/${index}.png`);
    uploads.push(
      putStorageObject(key, file, file.type || "image/png").then(() => {
        state = ensureResultKeyUrl(state, index, markS3Key(key));
        tick();
      }),
    );
  });

  if (input.videoFile) {
    const key = storageKey(input.identityId, input.cid, "video-source.mp4");
    uploads.push(
      putStorageObject(key, input.videoFile, input.videoFile.type || "video/mp4").then(tick),
    );
  }

  for (const [url, target] of serverUrls) {
    uploads.push(
      uploadFromUrl(input.identityId, input.cid, url, target).then((stored) => {
        state = replaceUrl(state, url, stored);
        tick();
      }),
    );
  }

  await Promise.all(uploads);
  await putConversationState(input.identityId, input.cid, state);
  return state;
}

function ensureResultKeyUrl(
  state: ConversationState,
  index: number,
  value: string,
): ConversationState {
  if (!state.result) return state;
  return {
    ...state,
    upload: state.upload
      ? {
          ...state.upload,
          thumbs: state.upload.thumbs.map((thumb, thumbIndex) =>
            thumbIndex === index ? value : thumb,
          ),
        }
      : state.upload,
    result: {
      ...state.result,
      key_urls: {
        ...(state.result.key_urls ?? {}),
        [String(index)]: state.result.key_urls?.[String(index)] ?? value,
      },
    },
  };
}

function stripSignedUrls(state: ConversationState): ConversationState {
  const stripValue = (value: string) => {
    const match = /#s3key=([^#]+)$/.exec(value);
    return match ? markS3Key(decodeURIComponent(match[1])) : value;
  };
  const stripOptional = (value: string | undefined) => (value ? stripValue(value) : undefined);
  const stripNullable = (value: string | null | undefined) =>
    value ? stripValue(value) : value;

  return {
    ...state,
    upload: state.upload
      ? { ...state.upload, thumbs: state.upload.thumbs.map(stripValue) }
      : state.upload,
    log: state.log.map((pair) => ({ ...pair, mid_url: stripNullable(pair.mid_url) })),
    result: state.result
      ? {
          ...state.result,
          artifacts: state.result.artifacts
            ? {
                montage: stripValue(state.result.artifacts.montage),
                video: stripValue(state.result.artifacts.video),
                report: stripOptional(state.result.artifacts.report),
              }
            : state.result.artifacts,
          explanations: state.result.explanations
            ? Object.fromEntries(
                Object.entries(state.result.explanations).map(([index, explanation]) => [
                  index,
                  { ...explanation, annotated_url: stripOptional(explanation.annotated_url) },
                ]),
              )
            : state.result.explanations,
          pair_mids: state.result.pair_mids
            ? Object.fromEntries(
                Object.entries(state.result.pair_mids).map(([index, url]) => [
                  index,
                  stripValue(url),
                ]),
              )
            : state.result.pair_mids,
          key_urls: state.result.key_urls
            ? Object.fromEntries(
                Object.entries(state.result.key_urls).map(([index, url]) => [
                  index,
                  stripValue(url),
                ]),
              )
            : state.result.key_urls,
        }
      : state.result,
  };
}

async function resolveValue(value: string | null | undefined) {
  const key = unmarkS3Key(value);
  return key ? getSignedStorageUrl(key) : value;
}

export async function resolveSignedUrls(state: ConversationState): Promise<ConversationState> {
  const result = state.result;
  if (!result) return state;

  const artifacts = result.artifacts
    ? {
        montage: (await resolveValue(result.artifacts.montage)) ?? result.artifacts.montage,
        video: (await resolveValue(result.artifacts.video)) ?? result.artifacts.video,
        report: (await resolveValue(result.artifacts.report)) ?? result.artifacts.report,
      }
    : result.artifacts;

  const explanations = result.explanations
    ? Object.fromEntries(
        await Promise.all(
          Object.entries(result.explanations).map(async ([idx, ex]) => [
            idx,
            {
              ...ex,
              annotated_url: (await resolveValue(ex.annotated_url)) ?? ex.annotated_url,
            },
          ]),
        ),
      )
    : result.explanations;

  const pair_mids = result.pair_mids
    ? Object.fromEntries(
        await Promise.all(
          Object.entries(result.pair_mids).map(async ([idx, url]) => [
            idx,
            (await resolveValue(url)) ?? url,
          ]),
        ),
      )
    : result.pair_mids;

  const key_urls = result.key_urls
    ? Object.fromEntries(
        await Promise.all(
          Object.entries(result.key_urls).map(async ([idx, url]) => [
            idx,
            (await resolveValue(url)) ?? url,
          ]),
        ),
      )
    : result.key_urls;

  const log = await Promise.all(
    state.log.map(async (p) => ({
      ...p,
      mid_url: (await resolveValue(p.mid_url)) ?? p.mid_url,
    })),
  );

  const upload = state.upload
    ? {
        ...state.upload,
        thumbs: await Promise.all(state.upload.thumbs.map((thumb) => resolveValue(thumb))),
      }
    : state.upload;

  return {
    ...state,
    upload: upload ? { ...upload, thumbs: upload.thumbs.filter((thumb): thumb is string => !!thumb) } : upload,
    log,
    result: {
      ...result,
      artifacts,
      explanations,
      pair_mids,
      key_urls,
    },
  };
}

export function makeConversationMeta(input: {
  identityId: string;
  cid: string;
  title: string;
  kind: SessionKind;
  engines: string;
  fps: number;
  stride: number;
  sid?: string | null;
  uploadLabel: string;
  thumb?: string | null;
  createdAt?: number;
}) {
  const now = Date.now();
  return {
    identityId: input.identityId,
    sk: conversationSk(input.cid),
    cid: input.cid,
    title: input.title,
    kind: input.kind,
    engines: input.engines,
    fps: input.fps,
    stride: input.stride,
    sid: input.sid ?? null,
    uploadLabel: input.uploadLabel,
    thumb: input.thumb ?? null,
    createdAt: input.createdAt ?? now,
    updatedAt: now,
    schemaVersion: SCHEMA_VERSION,
  } satisfies ConversationMeta;
}
